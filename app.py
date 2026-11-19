# -*- coding: utf-8 -*-
"""
OptiRuta Delivery - nuevo frontend Streamlit
--------------------------------------------
Este archivo reúne los cuatro perfiles y los módulos acordados para OptiRuta.

IMPORTANTE:
- Configurá API_URL y API_KEY en .streamlit/secrets.toml.
- Este frontend envía token de sesión cuando está disponible.
- Las acciones se envían al endpoint de Apps Script indicado por API_URL.
- Las acciones marcadas como "legacy" deben existir en el dispatcher actual de
  Apps Script. Las acciones nuevas deben agregarse al doPost(e) antes de producción.
- No se confía en el rol enviado por el navegador: Apps Script debe validar token,
  rol, propiedad del registro y permisos en cada operación.
"""

from __future__ import annotations

import math
import re
import unicodedata
import uuid
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# CONFIGURACIÓN E IDENTIDAD VISUAL
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="OptiRuta Delivery",
    page_icon="🛵",
    layout="wide",
    initial_sidebar_state="expanded",
)

AZUL = "#0750B8"
DORADO = "#E9A817"

st.markdown(
    f"""
    <style>
      :root {{ --or-blue: {AZUL}; --or-gold: {DORADO}; }}
      .stApp {{ background: #f5f7fb; }}
      [data-testid="stSidebar"] {{ background: #10243f; }}
      [data-testid="stSidebar"] * {{ color: #ffffff; }}
      .or-brand {{
        background: linear-gradient(110deg, #073b86, {AZUL});
        color: white; padding: 1.1rem 1.35rem; border-radius: 16px;
        border-bottom: 5px solid {DORADO}; margin-bottom: 1rem;
      }}
      .or-brand h1 {{ color: white; margin: 0; font-size: 1.8rem; }}
      .or-brand p {{ color: #eaf1ff; margin: .25rem 0 0 0; }}
      .or-card {{
        background: white; border: 1px solid #e4eaf2; border-radius: 14px;
        padding: 1rem; box-shadow: 0 2px 9px rgba(20,45,80,.05);
      }}
      .or-muted {{ color: #64748b; font-size: .9rem; }}
      div.stButton > button[kind="primary"] {{
        background: {AZUL}; border-color: {AZUL}; color: white;
      }}
      div[data-testid="stMetric"] {{
        background: white; padding: .8rem; border-radius: 12px;
        border: 1px solid #e4eaf2;
      }}
      .or-float {{
        position: fixed; right: 12px; bottom: 16px; z-index: 999;
        display: flex; flex-direction: column; gap: 8px;
      }}
      .or-float a {{
        background: #0b3977; color: white; border: 2px solid {DORADO};
        border-radius: 12px; padding: 9px 12px; text-decoration: none;
        font-weight: 700; box-shadow: 0 3px 12px #0002;
      }}
      @media (max-width: 700px) {{
        .or-brand h1 {{ font-size: 1.35rem; }}
        .or-float {{ right: 5px; bottom: 6px; }}
        .or-float a {{ padding: 7px 9px; font-size: .78rem; }}
      }}
    </style>
    """,
    unsafe_allow_html=True,
)


def brand_header(subtitle: str = "Gestión inteligente de entregas") -> None:
    st.markdown(
        f'<div class="or-brand"><h1>🛵 OptiRuta Delivery</h1>'
        f'<p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def cfg(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


API_URL = cfg("API_URL")
API_KEY = cfg("API_KEY")
TIMEOUT = int(cfg("API_TIMEOUT", "35") or "35")

# ---------------------------------------------------------------------------
# ESTADO DE SESIÓN Y CLIENTE API
# --------------------------------------------------------------------------------------

DEFAULT_STATE = {
    "logged_in": False,
    "user": None,
    "token": "",
    "staff_token": "",
    "page": "Inicio",
    "chat_unread": 0,
    "alerts_unread": 0,
}
for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


class OptiRutaAPIError(Exception):
    pass


def api(action: str, **kwargs: Any) -> Any:
    """Envía una acción al Web App de Apps Script."""
    if not API_URL:
        raise OptiRutaAPIError(
            "Falta API_URL. Configurá API_URL y API_KEY en .streamlit/secrets.toml."
        )
    payload = {"action": action}
    if API_KEY:
        payload["api_key"] = API_KEY
    token = st.session_state.get("token") or st.session_state.get("staff_token")
    if token:
        payload["token"] = token
    payload.update(kwargs)
    try:
        response = requests.post(API_URL, json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError as exc:
            raise OptiRutaAPIError(
                f"Apps Script devolvió una respuesta que no es JSON: {response.text[:300]}"
            ) from exc
    except requests.RequestException as exc:
        raise OptiRutaAPIError(f"No se pudo conectar con Apps Script: {exc}") from exc

    if isinstance(result, dict):
        status = str(result.get("status", "")).lower()
        if status in {"error", "failed", "fail"} or result.get("ok") is False:
            raise OptiRutaAPIError(
                result.get("message") or result.get("error") or "La operación fue rechazada."
            )
        if status == "ok":
            for key in ("data", "result", "record", "rows"):
                if key in result:
                    return result[key]
    return result


def safe_api(action: str, **kwargs: Any) -> tuple[bool, Any]:
    try:
        return True, api(action, **kwargs)
    except Exception as exc:
        st.error(str(exc))
        return False, None


def rows(sheet: str) -> list[dict]:
    """Lectura compatible con el dispatcher antiguo; backend debe filtrar por token."""
    result = api("list", sheet=sheet)
    if isinstance(result, dict):
        result = result.get("rows", result.get("data", []))
    return result if isinstance(result, list) else []


def df(sheet: str) -> pd.DataFrame:
    try:
        return pd.DataFrame(rows(sheet))
    except Exception as exc:
        st.warning(f"No se pudo consultar {sheet}: {exc}")
        return pd.DataFrame()


def save(sheet: str, record: dict) -> Any:
    """Compatibilidad con la acción save existente. No usar para saltar permisos."""
    return api("save", sheet=sheet, record=record)


def money(value: Any) -> str:
    try:
        amount = float(str(value or 0).replace(".", "").replace(",", "."))
    except (TypeError, ValueError):
        amount = 0
    return "Gs. " + f"{amount:,.0f}".replace(",", ".")


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).strip().lower()


def user_value(*keys: str, default: str = "") -> str:
    user = st.session_state.get("user") or {}
    for key in keys:
        value = user.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def current_role() -> str:
    return user_value("Rol", "role", "Role", "Tipo_Usuario").upper()


def current_id() -> str:
    return user_value(
        "ID_Usuario", "ID_Emprendedor", "ID_Conductor", "ID_Operador",
        "reference_id", "id", "ID"
    )


def do_logout() -> None:
    token = st.session_state.get("token") or st.session_state.get("staff_token")
    if token:
        try:
            api("logout")
        except Exception:
            pass
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


def show_table(data: Any, empty: str = "No hay registros para mostrar.") -> None:
    if isinstance(data, pd.DataFrame):
        frame = data
    elif isinstance(data, list):
        frame = pd.DataFrame(data)
    elif isinstance(data, dict):
        frame = pd.DataFrame(data.get("rows", data.get("data", [])))
    else:
        frame = pd.DataFrame()
    if frame.empty:
        st.info(empty)
    else:
        st.dataframe(frame, use_container_width=True, hide_index=True)


def metric_row(items: list[tuple[str, Any]]) -> None:
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.metric(label, value)


def status_badge(value: Any) -> str:
    return str(value or "Sin estado")


def require_config() -> bool:
    if not API_URL:
        st.error(
            "Todavía falta configurar la conexión. Creá "
            "`.streamlit/secrets.toml` con API_URL y API_KEY."
        )
        st.code('API_URL = "URL_DE_TU_WEB_APP"\nAPI_KEY = "TU_API_KEY"')
        return False
    return True


# ---------------------------------------------------------------------------
# LOGIN
# ---------------------------------------------------------------------------

ROLE_LABELS = {
    "ADMIN": "Administrador",
    "EMPRENDEDOR": "Emprendedor",
    "CONDUCTOR": "Conductor",
    "OPERADOR": "Operador",
}


def login_screen() -> None:
    brand_header("Plataforma de administración y logística")
    left, center, right = st.columns([1, 1.2, 1])
    with center:
        st.markdown("### Ingresar a OptiRuta")
        with st.form("login_form"):
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
        if submitted:
            if not username or not password:
                st.warning("Ingresá tu usuario y contraseña.")
                return
            if not require_config():
                return
            try:
                result = api("login", username=username, password=password)
                if not isinstance(result, dict):
                    raise OptiRutaAPIError("La respuesta de login no contiene los datos de sesión.")
                token = result.get("token") or result.get("session_token") or ""
                user = result.get("user") or result.get("usuario") or result
                role = str(user.get("Rol") or user.get("role") or user.get("Role") or "").upper()
                if role not in ROLE_LABELS:
                    raise OptiRutaAPIError("El backend no devolvió un rol válido.")
                st.session_state["user"] = user
                st.session_state["token"] = token
                st.session_state["logged_in"] = True
                st.session_state["page"] = "Inicio"
                # El backend nuevo debe devolver token para todos los roles.
                if not token:
                    st.warning(
                        "El acceso fue aceptado, pero Apps Script no devolvió token. "
                        "Las operaciones protegidas pueden fallar hasta corregir el login."
                    )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.caption("Acceso protegido por usuario y contraseña de OptiRuta.")


# ---------------------------------------------------------------------------
# COMPONENTES COMUNES
# ---------------------------------------------------------------------------

def sidebar(role: str) -> str:
    menus = {
        "ADMIN": [
            "Resumen", "Caja y movimientos", "Cierres de caja", "Liquidaciones",
            "Comisiones de operadores", "Operaciones por emprendedor", "Emprendedores",
            "Conductores", "Operadores", "Motos", "Usuarios", "Historial"
        ],
        "EMPRENDEDOR": ["Inicio", "Enviar pedidos", "Recibir levantes", "Mis operaciones"],
        "CONDUCTOR": ["Inicio", "Mi jornada", "Mis trabajos", "Mis ganancias", "Mi historial"],
        "OPERADOR": [
            "Inicio", "Panel operativo", "Trabajos y asignaciones", "Conductores y motos",
            "Jornadas", "Incidencias", "Historial operativo"
        ],
    }
    with st.sidebar:
        st.markdown("## 🛵 OptiRuta")
        st.caption(f"{ROLE_LABELS.get(role, role)}")
        st.write(user_value("Nombre", "Nombre_Completo", "name", default="Usuario"))
        st.divider()
        page = st.radio("Menú", menus.get(role, ["Inicio"]), key=f"menu_{role}")
        st.divider()
        if st.button("Cerrar sesión", use_container_width=True):
            do_logout()
    return page


def floating_access() -> None:
    st.markdown(
        """
        <div class="or-float">
          <a href="#chat-optiruta">💬 Chat</a>
          <a href="#alertas-optiruta">🔔 Alertas</a>
          <a href="#ganancias-optiruta">💰 Ganancias</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def common_notifications() -> None:
    with st.expander("🔔 Alertas y notificaciones", expanded=False):
        st.markdown('<div id="alertas-optiruta"></div>', unsafe_allow_html=True)
        ok, data = safe_api("notifications_list", only_unread=True)
        if ok:
            show_table(data, "No tenés alertas pendientes.")
            if st.button("Marcar todas como leídas"):
                safe_api("notifications_read_all")
                st.rerun()
    with st.expander("💬 Chat interno", expanded=False):
        st.markdown('<div id="chat-optiruta"></div>', unsafe_allow_html=True)
        st.info(
            "Espacio preparado para el chat interno. Para habilitar mensajes en tiempo real, "
            "el dispatcher de Apps Script debe implementar las acciones de chat."
        )


# ---------------------------------------------------------------------------
# ADMIN
# ---------------------------------------------------------------------------

def admin_dashboard() -> None:
    brand_header("Panel administrativo · Finanzas y control")
    pedidos = df("PEDIDOS")
    conductores = df("CONDUCTORES")
    emprendedores = df("EMPRENDEDORES")
    levantes = df("LEVANTES")
    metric_row([
        ("Pedidos registrados", len(pedidos)),
        ("Levantes registrados", len(levantes)),
        ("Conductores", len(conductores)),
        ("Emprendedores", len(emprendedores)),
    ])
    st.subheader("Actividad reciente")
    if not pedidos.empty:
        st.dataframe(pedidos.tail(10), use_container_width=True, hide_index=True)
    else:
        st.info("Todavía no hay pedidos registrados.")


def admin_cash() -> None:
    brand_header("Caja y movimientos")
    tabs = st.tabs(["Movimientos", "Registrar movimiento", "Cierres pendientes"])
    with tabs[0]:
        show_table(df("MOVIMIENTOS"))
    with tabs[1]:
        with st.form("admin_movement"):
            movement_type = st.selectbox(
                "Tipo de movimiento",
                ["TRANSFERENCIA_EMPRENDEDOR", "AJUSTE", "OTRO"]
            )
            entrepreneur_id = st.text_input("ID del emprendedor (si corresponde)")
            driver_id = st.text_input("ID del conductor (si corresponde)")
            amount = st.number_input("Monto (Gs.)", min_value=0, step=1000)
            method = st.selectbox("Método", ["TRANSFERENCIA", "EFECTIVO", "MIXTO"])
            reference = st.text_input("Referencia")
            notes = st.text_area("Observaciones")
            submit = st.form_submit_button("Registrar movimiento", type="primary")
        if submit:
            record = {
                "Tipo_Movimiento": movement_type,
                "ID_Emprendedor": entrepreneur_id,
                "ID_Conductor": driver_id,
                "Monto": amount,
                "Metodo_Pago": method,
                "Referencia": reference,
                "Observaciones": notes,
            }
            safe_api("movement", record=record)
    with tabs[2]:
        ok, result = safe_api("cashout_pending")
        if ok:
            show_table(result, "No hay cierres pendientes.")
        st.caption("La confirmación física y el cierre definitivo son funciones exclusivas de ADMIN.")


def admin_closures() -> None:
    brand_header("Cierres de caja")
    ok, pending = safe_api("cashout_pending")
    if ok:
        show_table(pending, "No hay cierres pendientes de verificación.")
    st.divider()
    st.subheader("Confirmar recepción")
    with st.form("confirm_cashout"):
        close_id = st.text_input("ID_Cierre_Caja")
        received = st.number_input("Efectivo recibido (Gs.)", min_value=0, step=1000)
        notes = st.text_area("Observaciones del cajero")
        submit = st.form_submit_button("Confirmar recepción", type="primary")
    if submit:
        safe_api(
            "cashout_confirm",
            ID_Cierre_Caja=close_id,
            efectivo_recibido=received,
            observaciones=notes,
        )


def admin_liquidations() -> None:
    brand_header("Liquidaciones")
    ok, result = safe_api("admin_liquidations_list")
    if ok:
        show_table(result, "No hay liquidaciones registradas.")
    st.divider()
    st.subheader("Crear borrador")
    with st.form("create_liquidation"):
        kind = st.selectbox("Tipo", ["CONDUCTOR", "EMPRENDEDOR"])
        driver = st.text_input("ID del conductor")
        entrepreneur = st.text_input("ID del emprendedor")
        closure = st.text_input("ID del cierre de caja")
        notes = st.text_area("Observaciones")
        submit = st.form_submit_button("Crear borrador")
    if submit:
        safe_api(
            "admin_liquidation_create",
            data={
                "Tipo_Liquidacion": kind,
                "ID_Conductor": driver,
                "ID_Emprendedor": entrepreneur,
                "ID_Cierre_Caja": closure,
                "Observaciones": notes,
            },
        )
    st.warning(
        "El backend debe calcular los importes desde los registros reales; "
        "no se permiten importes financieros definidos por el navegador."
    )


def admin_commissions() -> None:
    brand_header("Comisiones de operadores")
    ok, result = safe_api("admin_operator_commissions")
    if ok:
        show_table(result, "No hay comisiones generadas.")
    with st.form("commission_action"):
        commission_id = st.text_input("ID_Comision")
        action = st.selectbox("Acción", ["Autorizar", "Registrar pago"])
        notes = st.text_area("Observaciones")
        submit = st.form_submit_button("Ejecutar acción", type="primary")
    if submit:
        if action == "Autorizar":
            safe_api("admin_operator_commission_authorize", commission_id=commission_id, observations=notes)
        else:
            safe_api("admin_operator_commission_pay", commission_id=commission_id, observations=notes)


def admin_entrepreneur_operations() -> None:
    brand_header("Operaciones por emprendedor")
    with st.form("entrepreneur_daily_ops"):
        entrepreneur_id = st.text_input("ID del emprendedor")
        start = st.date_input("Desde", value=date.today())
        end = st.date_input("Hasta", value=date.today())
        submit = st.form_submit_button("Consultar")
    if submit:
        ok, result = safe_api(
            "admin_entrepreneur_daily_operations",
            ID_Emprendedor=entrepreneur_id,
            fecha_desde=start.isoformat(),
            fecha_hasta=end.isoformat(),
        )
        if ok:
            show_table(result, "No hay operaciones en ese período.")


def admin_master_data(section: str, sheet: str, fields: list[tuple[str, str]]) -> None:
    brand_header(section)
    with st.form(f"create_{sheet.lower()}"):
        values = {}
        for key, label in fields:
            values[key] = st.text_input(label)
        submit = st.form_submit_button(f"Registrar {section.lower()}", type="primary")
    if submit:
        record = dict(values)
        record.setdefault("ID", str(uuid.uuid4()))
        safe_api("save", sheet=sheet, record=record)
    show_table(df(sheet))


def admin_users() -> None:
    brand_header("Usuarios y accesos")
    with st.form("create_user"):
        username = st.text_input("Nombre de usuario")
        password = st.text_input("Contraseña temporal", type="password")
        role = st.selectbox("Perfil", ["EMPRENDEDOR", "CONDUCTOR", "OPERADOR"])
        reference = st.text_input("ID vinculado (emprendedor, conductor u operador)")
        submit = st.form_submit_button("Crear acceso", type="primary")
    if submit:
        safe_api(
            "create_user", username=username, password=password,
            role=role, reference_id=reference
        )
    show_table(df("USUARIOS"))


def admin_history() -> None:
    brand_header("Historial y auditoría")
    ok, result = safe_api("history_list")
    if ok:
        show_table(result, "No hay eventos de historial disponibles.")
    st.caption("El historial debe registrar actor, rol, fecha, módulo, acción y referencia.")


def render_admin(page: str) -> None:
    if page == "Resumen":
        admin_dashboard()
    elif page == "Caja y movimientos":
        admin_cash()
    elif page == "Cierres de caja":
        admin_closures()
    elif page == "Liquidaciones":
        admin_liquidations()
    elif page == "Comisiones de operadores":
        admin_commissions()
    elif page == "Operaciones por emprendedor":
        admin_entrepreneur_operations()
    elif page == "Emprendedores":
        admin_master_data("Emprendedores", "EMPRENDEDORES", [
            ("Nombre", "Nombre del emprendedor"), ("Telefono", "Teléfono"),
            ("Direccion", "Dirección"),
        ])
    elif page == "Conductores":
        admin_master_data("Conductores", "CONDUCTORES", [
            ("CI", "Cédula de identidad (CI)"), ("Nombre_Completo", "Nombre completo"),
            ("Telefono", "Teléfono"),
        ])
        st.info("La CI debe ser única e inmutable. Para un reingreso se reactiva el mismo registro.")
    elif page == "Operadores":
        admin_master_data("Operadores", "OPERADORES", [
            ("Nombre", "Nombre del operador"), ("Telefono", "Teléfono"),
        ])
    elif page == "Motos":
        admin_master_data("Motos", "MOTOS", [
            ("Descripcion", "Descripción"), ("Patente", "Patente"),
            ("Propiedad", "Propiedad"), ("Propietario", "Propietario"),
        ])
    elif page == "Usuarios":
        admin_users()
    elif page == "Historial":
        admin_history()


# ---------------------------------------------------------------------------
# EMPRENDEDOR
# ---------------------------------------------------------------------------

def entrepreneur_home() -> None:
    brand_header("Portal del emprendedor")
    st.markdown("## ¿En qué te puedo ayudar hoy?")
    a, b = st.columns(2)
    with a:
        if st.button("📦 ENVIAR · Crear pedido", type="primary", use_container_width=True):
            st.session_state["entrepreneur_action"] = "Enviar pedidos"
            st.rerun()
    with b:
        if st.button("🛍️ RECIBIR · Solicitar levante", type="primary", use_container_width=True):
            st.session_state["entrepreneur_action"] = "Recibir levantes"
            st.rerun()


def entrepreneur_order() -> None:
    brand_header("Enviar un pedido")
    with st.form("entrepreneur_order_form"):
        customer = st.text_input("Nombre del cliente")
        phone = st.text_input("Teléfono del cliente")
        address = st.text_input("Dirección de entrega")
        maps = st.text_input("Ubicación de Google Maps (enlace)")
        description = st.text_area("Descripción del pedido")
        priority = st.selectbox("Prioridad", ["Normal", "Urgente"])
        product_amount = st.number_input("Costo del producto (Gs.)", min_value=0, step=1000)
        shipping = st.number_input("Costo de envío (Gs.)", min_value=0, step=1000, value=15000)
        advance = st.number_input("Monto anticipado (Gs.)", min_value=0, step=1000)
        payment = st.selectbox(
            "Forma de pago",
            ["Efectivo al recibir", "Transferencia al emprendedor",
             "Efectivo + transferencia", "Pagado adelantado"],
        )
        transfer = st.number_input("Monto transferido (Gs.)", min_value=0, step=1000)
        instructions = st.text_area("Instrucciones para el conductor")
        submit = st.form_submit_button("Enviar pedido", type="primary")
    if submit:
        if not customer or not phone or not address:
            st.warning("Completá nombre, teléfono y dirección.")
        else:
            record = {
                "ID_Pedido": str(uuid.uuid4()),
                "ID_Emprendedor": current_id(),
                "Nombre_Cliente": customer,
                "Telefono_Cliente": phone,
                "Direccion_Entrega": address,
                "Ubicacion_Google_Maps": maps,
                "Descripcion": description,
                "Prioridad": priority,
                "Monto_Producto": product_amount,
                "Costo_Envio": shipping,
                "Monto_Anticipado": advance,
                "Metodo_Pago": payment,
                "Monto_Transferencia_Adicional": transfer,
                "Instrucciones": instructions,
                "Estado_Reparto": "Pendiente",
            }
            ok, _ = safe_api("entrepreneur_create_order", record=record)
            if not ok:
                st.caption("Compatibilidad alternativa: el backend anterior puede requerir la acción save.")
    st.subheader("Mis pedidos")
    ok, result = safe_api("entrepreneur_my_orders")
    if ok:
        show_table(result, "Todavía no tenés pedidos.")


def entrepreneur_levante() -> None:
    brand_header("Recibir · Solicitar levante")
    st.caption("El levante corresponde a una compra del emprendedor a su proveedor.")
    with st.form("entrepreneur_levante_form"):
        supplier = st.text_input("Nombre del proveedor")
        supplier_phone = st.text_input("Teléfono del proveedor")
        origin = st.text_input("Dirección de retiro")
        origin_maps = st.text_input("Ubicación de retiro (Google Maps)")
        origin_ref = st.text_input("Referencia del retiro")
        destination = st.text_input("Dirección de destino (a nombre del emprendedor)")
        destination_maps = st.text_input("Ubicación de destino (Google Maps)")
        destination_ref = st.text_input("Referencia del destino")
        reference_number = st.text_input("Número de referencia")
        requested_name = st.text_input("Nombre solicitado para retirar")
        total = st.number_input("Total de la compra (Gs.)", min_value=0, step=1000)
        priority = st.selectbox("Prioridad", ["Normal", "Urgente"])
        notes = st.text_area("Observaciones")
        photo = st.file_uploader("Foto de comprobante (una sola imagen)", type=["jpg", "jpeg", "png"])
        submit = st.form_submit_button("Enviar solicitud de levante", type="primary")
    if submit:
        if not supplier or not origin or not destination or not requested_name:
            st.warning("Completá proveedor, retiro, destino y nombre solicitado.")
        else:
            record = {
                "ID_Levante": str(uuid.uuid4()),
                "ID_Emprendedor": current_id(),
                "Nombre_Proveedor": supplier,
                "Telefono_Proveedor": supplier_phone,
                "Direccion_Origen": origin,
                "Ubicacion_Origen_Google_Maps": origin_maps,
                "Referencia_Origen": origin_ref,
                "Direccion_Destino": destination,
                "Ubicacion_Destino_Google_Maps": destination_maps,
                "Referencia_Destino": destination_ref,
                "Numero_Referencia": reference_number,
                "Nombre_Solicitado": requested_name,
                "Monto_Total": total,
                "Prioridad": priority,
                "Observaciones": notes,
                "Estado_Levante": "Pendiente",
                "Costo_Levante": 20000,
            }
            if photo:
                # La carga binaria necesita una acción de backend/Drive específica.
                st.warning("La foto se seleccionó, pero su almacenamiento requiere la acción de carga de archivos en Apps Script.")
            safe_api("entrepreneur_create_levante", record=record)
    st.info("Costo de referencia del trámite: Gs. 20.000. Pago de conductor definido: Gs. 10.000.")
    st.subheader("Mis solicitudes de RECIBIR")
    ok, result = safe_api("entrepreneur_my_levantes")
    if ok:
        show_table(result, "Todavía no tenés solicitudes de levante.")


def entrepreneur_operations() -> None:
    brand_header("Mis operaciones")
    a, b = st.tabs(["Pedidos", "Levantes"])
    with a:
        ok, result = safe_api("entrepreneur_my_orders")
        if ok:
            show_table(result)
    with b:
        ok, result = safe_api("entrepreneur_my_levantes")
        if ok:
            show_table(result)


def render_entrepreneur(page: str) -> None:
    page = st.session_state.get("entrepreneur_action", page)
    if page == "Inicio":
        entrepreneur_home()
    elif page == "Enviar pedidos":
        entrepreneur_order()
    elif page == "Recibir levantes":
        entrepreneur_levante()
    elif page == "Mis operaciones":
        entrepreneur_operations()


# ---------------------------------------------------------------------------
# CONDUCTOR
# ---------------------------------------------------------------------------

def driver_home() -> None:
    brand_header("Panel del conductor")
    ok, shift = safe_api("driver_my_active_shift")
    if ok:
        st.subheader("Mi jornada")
        st.write(shift if shift else "No hay una jornada activa.")
    ok, works = safe_api("driver_my_works")
    if ok:
        show_table(works, "No tenés trabajos activos asignados.")


def driver_shift() -> None:
    brand_header("Mi jornada")
    ok, shift = safe_api("driver_my_active_shift")
    if ok:
        st.write("Jornada actual")
        st.json(shift if shift else {})
    st.divider()
    device = st.text_input("Identificador del dispositivo (opcional)")
    a, b = st.columns(2)
    with a:
        if st.button("▶️ Iniciar turno", type="primary", use_container_width=True):
            safe_api("driver_start_shift", ID_Dispositivo=device)
    with b:
        reason = st.text_input("Motivo de finalización")
        if st.button("⏹ Finalizar mi turno", use_container_width=True):
            safe_api("driver_end_shift", motivo=reason)


def driver_works() -> None:
    brand_header("Mis trabajos")
    ok, result = safe_api("driver_my_works")
    if ok:
        show_table(result, "No hay trabajos activos.")
    st.divider()
    st.subheader("Actualizar estado de un trabajo")
    with st.form("driver_work_update"):
        work_type = st.selectbox("Tipo", ["PEDIDO", "LEVANTE", "TRAMITE"])
        reference = st.text_input("ID del pedido / levante / trámite")
        states = (
            ["En camino", "Entregado"] if work_type == "PEDIDO"
            else ["En camino", "En proceso", "Completado"]
        )
        new_state = st.selectbox("Nuevo estado", states)
        submit = st.form_submit_button("Actualizar estado", type="primary")
    if submit:
        safe_api(
            "driver_update_work_status",
            work_type=work_type,
            reference_id=reference,
            new_status=new_state,
        )
    st.caption(
        "El conductor no realiza cierres de caja ni liquidaciones. "
        "Los trabajos pendientes al terminar el turno se coordinan con OPERADOR."
    )


def driver_location() -> None:
    brand_header("Ubicación")
    st.info(
        "La ubicación compartida se usa para coordinar el servicio. "
        "No se presenta como seguimiento GPS en vivo si el backend no lo implementa."
    )
    lat = st.number_input("Latitud", format="%.7f")
    lon = st.number_input("Longitud", format="%.7f")
    if st.button("Compartir ubicación"):
        safe_api("location", record={
            "ID_Conductor": current_id(),
            "Latitud": lat,
            "Longitud": lon,
            "Fecha_Hora": datetime.now().isoformat(),
        })


def driver_earnings() -> None:
    brand_header("Mis ganancias")
    ok, result = safe_api("driver_my_earnings")
    if ok:
        if isinstance(result, dict):
            st.metric("Acumulado de la jornada", money(result.get("total", 0)))
        show_table(result, "Todavía no hay ganancias acreditadas.")
    st.markdown('<div id="ganancias-optiruta"></div>', unsafe_allow_html=True)


def driver_history() -> None:
    brand_header("Mi historial")
    ok, result = safe_api("driver_shift_history")
    if ok:
        show_table(result, "No hay jornadas anteriores.")


def render_driver(page: str) -> None:
    if page == "Inicio":
        driver_home()
    elif page == "Mi jornada":
        driver_shift()
    elif page == "Mis trabajos":
        driver_works()
    elif page == "Mis ganancias":
        driver_earnings()
    elif page == "Mi historial":
        driver_history()


# ---------------------------------------------------------------------------
# OPERADOR
# ---------------------------------------------------------------------------

def operator_home() -> None:
    brand_header("Panel operativo")
    ok, result = safe_api("operator_queue")
    if ok and isinstance(result, dict):
        active = result.get("active", [])
        queue = result.get("queue", [])
        commissions = result.get("commissions", [])
        metric_row([
            ("Trabajos activos", len(active)),
            ("En cola", len(queue)),
            ("Comisiones", len(commissions)),
        ])
        st.subheader("Trabajos activos")
        show_table(active, "No tenés trabajos activos.")
        st.subheader("Cola de trabajos")
        show_table(queue, "No hay trabajos pendientes.")
    else:
        st.info("El panel operativo necesita la acción operator_queue del dispatcher.")


def operator_work_management() -> None:
    brand_header("Trabajos y asignaciones")
    ok, result = safe_api("operator_queue")
    if ok and isinstance(result, dict):
        st.subheader("Cola de pedidos y levantes")
        queue = result.get("queue", [])
        show_table(queue, "No hay trabajos pendientes.")
        if queue:
            st.caption("Tomá un trabajo para comenzar su coordinación.")
    st.divider()
    st.subheader("Tomar un trabajo")
    with st.form("operator_take"):
        kind = st.selectbox("Tipo de trabajo", ["PEDIDO", "LEVANTE", "TRAMITE"])
        reference = st.text_input("ID de referencia")
        submit = st.form_submit_button("Tomar trabajo", type="primary")
    if submit:
        safe_api("operator_take", work_type=kind, reference_id=reference)
    st.divider()
    st.subheader("Asignar o reasignar conductor")
    with st.form("operator_assign"):
        kind2 = st.selectbox("Tipo de trabajo", ["PEDIDO", "LEVANTE", "TRAMITE"], key="assign_kind")
        reference2 = st.text_input("ID del trabajo", key="assign_ref")
        driver_id = st.text_input("ID del conductor")
        submit2 = st.form_submit_button("Asignar conductor")
    if submit2:
        safe_api(
            "operator_assign_work",
            work_type=kind2,
            reference_id=reference2,
            driver_id=driver_id,
        )
    st.divider()
    st.subheader("Observaciones")
    with st.form("operator_observation"):
        work_id = st.text_input("ID_Trabajo")
        observation = st.text_area("Observación")
        submit3 = st.form_submit_button("Guardar observación")
    if submit3:
        safe_api("operator_observation", work_id=work_id, text=observation)


def operator_drivers_motos() -> None:
    brand_header("Conductores y motos")
    a, b = st.tabs(["Conductores", "Motos"])
    with a:
        show_table(df("CONDUCTORES"))
    with b:
        show_table(df("MOTOS"))
    st.divider()
    st.subheader("Asignar moto a conductor")
    with st.form("operator_assign_moto"):
        driver_id = st.text_input("ID_Conductor")
        moto_id = st.text_input("ID_Moto")
        notes = st.text_area("Observaciones")
        submit = st.form_submit_button("Asignar moto", type="primary")
    if submit:
        safe_api("operator_assign_moto", ID_Conductor=driver_id, ID_Moto=moto_id, observaciones=notes)
    st.subheader("Cambiar moto")
    with st.form("operator_change_moto"):
        driver2 = st.text_input("ID_Conductor", key="change_driver")
        moto2 = st.text_input("Nueva ID_Moto")
        reason = st.text_input("Motivo del cambio")
        submit2 = st.form_submit_button("Cambiar moto")
    if submit2:
        safe_api("operator_change_moto", ID_Conductor=driver2, ID_Moto=moto2, motivo=reason)
    st.subheader("Recibir devolución")
    with st.form("operator_return_moto"):
        driver3 = st.text_input("ID_Conductor", key="return_driver")
        notes3 = st.text_area("Observaciones de devolución")
        submit3 = st.form_submit_button("Registrar devolución")
    if submit3:
        safe_api("operator_return_moto", ID_Conductor=driver3, observaciones=notes3)


def operator_shifts() -> None:
    brand_header("Jornadas de conductores")
    ok, result = safe_api("operator_active_shifts")
    if ok:
        show_table(result, "No hay jornadas activas.")
    st.divider()
    with st.form("operator_end_shift"):
        driver = st.text_input("ID_Conductor")
        reason = st.text_area("Motivo de finalización del turno")
        submit = st.form_submit_button("Finalizar turno del conductor", type="primary")
    if submit:
        safe_api("operator_end_driver_shift", ID_Conductor=driver, motivo=reason)
    st.caption("Finalizar turno no cierra caja ni autoriza liquidaciones.")


def operator_incidents() -> None:
    brand_header("Incidencias y coordinación")
    with st.form("operator_incident"):
        work_type = st.selectbox("Tipo", ["PEDIDO", "LEVANTE", "TRAMITE", "JORNADA", "MOTO"])
        reference = st.text_input("ID de referencia")
        category = st.selectbox(
            "Tipo de incidencia",
            ["Demora", "Proveedor cerrado", "Cliente ausente", "Problema con moto", "Otra"],
        )
        detail = st.text_area("Detalle")
        submit = st.form_submit_button("Registrar incidencia")
    if submit:
        safe_api(
            "operator_incident_create",
            tipo=work_type,
            referencia=reference,
            categoria=category,
            detalle=detail,
        )


def operator_history() -> None:
    brand_header("Historial operativo")
    ok, result = safe_api("history_operational_list")
    if ok:
        show_table(result, "No hay historial operativo disponible.")


def render_operator(page: str) -> None:
    if page == "Inicio":
        operator_home()
    elif page in ("Panel operativo", "Trabajos y asignaciones"):
        operator_work_management()
    elif page == "Conductores y motos":
        operator_drivers_motos()
    elif page == "Jornadas":
        operator_shifts()
    elif page == "Incidencias":
        operator_incidents()
    elif page == "Historial operativo":
        operator_history()


# ---------------------------------------------------------------------------
# APLICACIÓN PRINCIPAL
# ---------------------------------------------------------------------------

def main() -> None:
    if not st.session_state.get("logged_in"):
        login_screen()
        return

    role = current_role()
    if role not in ROLE_LABELS:
        st.error("Rol no reconocido. Contactá al administrador.")
        if st.button("Volver al inicio de sesión"):
            do_logout()
        return

    page = sidebar(role)
    if role == "ADMIN":
        render_admin(page)
    elif role == "EMPRENDEDOR":
        render_entrepreneur(page)
    elif role == "CONDUCTOR":
        render_driver(page)
    elif role == "OPERADOR":
        render_operator(page)

    common_notifications()
    floating_access()
    st.caption(
        f"OptiRuta Delivery · {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
        "Los permisos definitivos se validan en Apps Script."
    )


if __name__ == "__main__":
    main()
