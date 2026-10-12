# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spanish catalog of the admin panel and the `/` page (message id: the English text)."""

ES: dict[str, str] = {
    # Pages and navigation
    "Admin": "Administración",
    "Admin panel": "Panel de administración",
    "Sections": "Secciones",
    "Overview": "Resumen",
    "Users": "Usuarios",
    "API keys": "Claves de API",
    "Downloads": "Descargas",
    "Library": "Biblioteca",
    "yt-dlp": "yt-dlp",
    "Audit log": "Registro de auditoría",
    "Notifications": "Notificaciones",
    "Sign in": "Iniciar sesión",
    "Sign out": "Cerrar sesión",
    "Not allowed": "No permitido",
    "Not found": "No encontrado",
    "UltimateTunes server is running.": "El servidor de UltimateTunes está funcionando.",
    "Version %(version)s": "Versión %(version)s",
    "The panel needs HTTPS (for example tailscale serve) or localhost.": (
        "El panel necesita HTTPS (por ejemplo, tailscale serve) o localhost."
    ),
    # Common words
    "Username": "Usuario",
    "Password": "Contraseña",  # nosec B105 - a UI label, not a secret
    "User": "Usuario",
    "Administrator": "Administrador",
    "Role": "Rol",
    "Status": "Estado",
    "State": "Estado",
    "Actions": "Acciones",
    "Action": "Acción",
    "Active": "Activo",
    "Disabled": "Desactivado",
    "Enable": "Activar",
    "Disable": "Desactivar",
    "Created": "Creada",
    "Updated": "Actualizado",
    "Error": "Error",
    "Search": "Buscar",
    "Save": "Guardar",
    "Delete": "Borrar",
    "Sure": "Seguro",
    "Retry": "Reintentar",
    "Cancel": "Cancelar",
    "Revoke": "Revocar",
    "Revoked": "Revocada",
    "Nothing here.": "No hay nada.",
    "never": "nunca",
    "none yet": "ninguna todavía",
    "waiting": "en espera",
    "OK": "Bien",
    "Failed": "Fallida",
    "All": "Todas",
    "When": "Cuándo",
    "Who": "Quién",
    "From": "Desde",
    "Target": "Objeto",
    "Detail": "Detalle",
    "Message": "Mensaje",
    "Result": "Resultado",
    "Source": "Origen",
    "Version": "Versión",
    "Kind": "Tipo",
    "Off": "Desactivadas",
    "ntfy": "ntfy",
    "webhook": "webhook",
    # Overview
    "Tracks": "Canciones",
    "Albums": "Álbumes",
    "Artists": "Artistas",
    "Need review": "Por revisar",
    "Queued": "En cola",
    "Downloading": "Descargando",
    "YouTube Music": "YouTube Music",
    "Last canary run": "Última prueba canario",
    "Workers seen": "Workers vistos",
    "Search circuit breaker": "Cortacircuitos de búsqueda",
    "not in use (fake catalog)": "sin uso (catálogo falso)",
    "open: YouTube Music is throttling, searches show the library only": (
        "abierto: YouTube Music está limitando, las búsquedas solo muestran la biblioteca"
    ),
    "closed": "cerrado",
    # Users
    "Last sign-in": "Último inicio de sesión",
    "Make user": "Hacer usuario",
    "Make administrator": "Hacer administrador",
    "New password": "Contraseña nueva",
    "Set password": "Cambiar contraseña",
    "New user": "Usuario nuevo",
    "Password (12 characters or more)": "Contraseña (12 caracteres o más)",
    "Create user": "Crear usuario",
    # Keys
    "New key for %(name)s": "Clave nueva para %(name)s",
    "Copy it or scan the code now: it is shown only once.": (
        "Cópiala o escanea el código ahora: solo se muestra una vez."
    ),
    "Server address": "Dirección del servidor",
    "API key": "Clave de API",
    "Device": "Dispositivo",
    "Prefix": "Prefijo",
    "Last use": "Último uso",
    "No keys yet.": "Todavía no hay claves.",
    "New key (with a QR code for the app)": "Clave nueva (con código QR para la app)",
    "Device name": "Nombre del dispositivo",
    "Server address the app will use": "Dirección del servidor que usará la app",
    "Create key": "Crear clave",
    "QR code to connect the app": "Código QR para conectar la app",
    # Downloads
    "Song": "Canción",
    "Progress": "Progreso",
    "Attempts": "Intentos",
    "cancel requested": "cancelación pedida",
    "queued": "en cola",
    "downloading": "descargando",
    "tagging": "etiquetando",
    "ready": "lista",
    "failed": "fallida",
    "cancelled": "cancelada",
    # Library
    "Music files": "Archivos de música",
    "Disk used": "Disco usado",
    "Disk free": "Disco libre",
    "Album": "Álbum",
    "Find tracks and albums to delete": "Buscar canciones y álbumes para borrar",
    "%(count)s tracks": "%(count)s canciones",
    # yt-dlp
    "Update yt-dlp now": "Actualizar yt-dlp ahora",
    "Run the canary now": "Lanzar la prueba canario ahora",
    "Workers": "Workers",
    "Worker": "Worker",
    "Last report": "Último informe",
    "No worker has reported yet.": "Ningún worker ha informado todavía.",
    "Canary runs": "Pruebas canario",
    "Commands": "Órdenes",
    "Command": "Orden",
    "Requested": "Pedida",
    "Delivered": "Entregada",
    # Notifications
    "Failed downloads and failed canary runs can be sent to an ntfy topic or a webhook. "
    "The server contacts only this address.": (
        "Las descargas y pruebas canario fallidas pueden enviarse a un tema de ntfy o a un"
        " webhook. El servidor solo contacta con esta dirección."
    ),
    "URL (https only)": "URL (solo https)",
    "Send a test notification": "Enviar una notificación de prueba",
    "Credentials": "Credenciales",
    "Access token: set ✓": "Token de acceso: configurado ✓",
    "User and password: set ✓": "Usuario y contraseña: configurados ✓",
    "Credentials: not set": "Credenciales: sin configurar",
    "For an ntfy server that requires login, set UT_NOTIFY_TOKEN (an ntfy access token), or "
    "UT_NOTIFY_USERNAME and UT_NOTIFY_PASSWORD, as Docker secrets or environment variables, "
    "and restart the api. They go only to the address above, over https, and also to a "
    "webhook.": (
        "Para un servidor ntfy que pide inicio de sesión, define UT_NOTIFY_TOKEN (un token de"
        " acceso de ntfy), o UT_NOTIFY_USERNAME y UT_NOTIFY_PASSWORD, como secretos de Docker o"
        " variables de entorno, y reinicia la api. Solo se envían a la dirección de arriba, por"
        " https, y también a un webhook."
    ),
    "They cannot be entered here: this server has no encryption library to keep them safe in "
    "its database.": (
        "No se pueden introducir aquí: este servidor no tiene una biblioteca de cifrado para"
        " guardarlas de forma segura en su base de datos."
    ),
    # Confirmations (?done=)
    "User created.": "Usuario creado.",
    "User updated.": "Usuario actualizado.",
    "Key revoked.": "Clave revocada.",
    "Download queued again.": "Descarga puesta de nuevo en cola.",
    "Cancel requested.": "Cancelación pedida.",
    "Track deleted.": "Canción borrada.",
    "Album deleted.": "Álbum borrado.",
    "Deleted, but some files could not be removed from disk (see the logs).": (
        "Borrado, pero algunos archivos no se pudieron quitar del disco (mira los registros)."
    ),
    "Command queued: the next worker report picks it up.": (
        "Orden en cola: el próximo informe de un worker la recoge."
    ),
    "That command is already waiting for a worker.": "Esa orden ya espera a un worker.",
    "Notification settings saved.": "Notificaciones guardadas.",
    "Test notification sent.": "Notificación de prueba enviada.",
    "The test notification could not be delivered.": (
        "No se pudo entregar la notificación de prueba."
    ),
    "ntfy rejected the credentials (HTTP 401 or 403). Check the access token, or the user and"
    " password, and that this user may write to the topic.": (
        "ntfy rechazó las credenciales (HTTP 401 o 403). Revisa el token de acceso, o el usuario"
        " y la contraseña, y que ese usuario pueda escribir en el tema."
    ),
    "The webhook rejected the credentials (HTTP 401 or 403).": (
        "El webhook rechazó las credenciales (HTTP 401 o 403)."
    ),
    # Errors
    "Wrong username or password.": "Usuario o contraseña incorrectos.",
    "Too many attempts. Wait and try again.": "Demasiados intentos. Espera y vuelve a probar.",
    "This account is not an administrator.": "Esta cuenta no es de administrador.",
    "Your session has ended. Sign in again.": "Tu sesión ha terminado. Vuelve a iniciarla.",
    "The form expired or came from another site. Reload and retry.": (
        "El formulario caducó o venía de otro sitio. Recarga y vuelve a probar."
    ),
    "You cannot disable yourself or change your own role": (
        "No puedes desactivarte ni cambiar tu propio rol"
    ),
    "Unknown action": "Acción desconocida",
    "The server address must be an https URL of at most 120 characters": (
        "La dirección del servidor debe ser una URL https de 120 caracteres como mucho"
    ),
    "The server address is too long": "La dirección del servidor es demasiado larga",
    "No such job": "No existe esa descarga",
    "Only failed or cancelled downloads can be retried": (
        "Solo se pueden reintentar descargas fallidas o canceladas"
    ),
    "Only queued or running downloads can be cancelled": (
        "Solo se pueden cancelar descargas en cola o en curso"
    ),
    "Tick the box to confirm the delete": "Marca la casilla para confirmar el borrado",
    "The album changed meanwhile; try again": "El álbum cambió mientras tanto; vuelve a probar",
    "Notifications cannot go to this server's own network": (
        "Las notificaciones no pueden ir a la red local de este servidor"
    ),
    "Set a notification target first": "Configura antes un destino de notificaciones",
    "A download of this item is in progress; cancel it first": (
        "Hay una descarga de esto en curso; cancélala primero"
    ),
    "No such track": "No existe esa canción",
    "No such album": "No existe ese álbum",
    "The URL is empty or too long": "La URL está vacía o es demasiado larga",
    "The URL must start with https://": "La URL debe empezar por https://",
    "The URL must not contain a user or password": "La URL no puede llevar usuario ni contraseña",
    "The URL must not contain spaces": "La URL no puede llevar espacios",
    "Unknown notification kind": "Tipo de notificación desconocido",
    # Errors of T04's AuthService shown in the panel
    "That username is taken": "Ese nombre de usuario ya existe",
    "No such user": "No existe ese usuario",
    "No such key": "No existe esa clave",
    "The role must be admin or user": "El rol debe ser admin o user",
}
