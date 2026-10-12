# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spanish catalog of the admin panel and the `/` page (message id: the English text)."""

ES: dict[str, str] = {
    # Overview, limits and production polish (layout, lists, confirmations)
    "Skip to content": "Saltar al contenido",
    "Needs attention": "Requiere atención",
    "Everything looks fine.": "Todo parece en orden.",
    "Details": "Detalles",
    "%(count)s failed downloads": "%(count)s descargas fallidas",
    "%(count)s tracks need review": "%(count)s canciones por revisar",
    "Downloads are paused: low disk space since %(since)s.": (
        "Las descargas están en pausa: poco espacio en disco desde %(since)s."
    ),
    "Downloads are paused: low disk space since %(since)s. Free space on /music or /staging"
    " (minimum %(minimum)s).": (
        "Las descargas están en pausa: poco espacio en disco desde %(since)s. Libera espacio en"
        " /music o /staging (mínimo %(minimum)s)."
    ),
    "%(disk)s is below the free-space minimum (%(minimum)s): new downloads will be refused.": (
        "%(disk)s está por debajo del espacio libre mínimo (%(minimum)s): se rechazarán las"
        " descargas nuevas."
    ),
    "Below %(minimum)s free on either volume, new downloads are refused and workers stop"
    " claiming (UT_MIN_FREE_BYTES).": (
        "Con menos de %(minimum)s libres en cualquiera de los dos volúmenes, se rechazan las"
        " descargas nuevas y los workers dejan de tomar trabajos (UT_MIN_FREE_BYTES)."
    ),
    "YouTube Music is throttling this server: searches show the library only for now.": (
        "YouTube Music está limitando a este servidor: por ahora las búsquedas muestran solo la"
        " biblioteca."
    ),
    "The shared YouTube Music request budget is used up: lookups are waiting for it to refill.": (
        "Se ha agotado el cupo compartido de peticiones a YouTube Music: las consultas esperan a"
        " que se recargue."
    ),
    "The last canary run failed (%(when)s).": "La última ejecución del canario falló (%(when)s).",
    "No worker has reported yet: downloads will wait in the queue.": (
        "Ningún worker ha informado todavía: las descargas esperarán en la cola."
    ),
    "Downloaded in 24 h": "Descargado en 24 h",
    "Disk space": "Espacio en disco",
    "Volume": "Volumen",
    "Free": "Libre",
    "Size": "Tamaño",
    "Low": "Bajo",
    "Shared request budget": "Cupo compartido de peticiones",
    "last report %(when)s": "último informe %(when)s",
    "you": "tú",
    "Catalog / search left": "Catálogo / búsquedas restantes",
    "Downloads: queued or running jobs, and bytes downloaded in the last 24 hours, against the"
    " per-user limits. Catalog and search: requests left in each user's YouTube Music budget"
    " (they refill over time).": (
        "Descargas: trabajos en cola o en curso, y bytes descargados en las últimas 24 horas,"
        " frente a los límites por usuario. Catálogo y búsquedas: peticiones que le quedan a"
        " cada usuario en su cupo de YouTube Music (se recargan con el tiempo)."
    ),
    "Disable %(name)s? Their API keys stop working until you enable the account again.": (
        "¿Desactivar a %(name)s? Sus claves de API dejan de funcionar hasta que vuelvas a"
        " activar la cuenta."
    ),
    "Change the role of %(name)s?": "¿Cambiar el rol de %(name)s?",
    "New password for %(name)s": "Nueva contraseña para %(name)s",
    "Next: give each of their devices its own API key, on the API keys page.": (
        "Después: dale a cada uno de sus dispositivos su propia clave en la página Claves de API."
    ),
    "One key per device. Revoking a key signs that device out at once; the others keep working.": (
        "Una clave por dispositivo. Revocar una clave desconecta ese dispositivo al momento; los"
        " demás siguen funcionando."
    ),
    "Revoke the key of %(device)s? That device stops working until it gets a new key.": (
        "¿Revocar la clave de %(device)s? Ese dispositivo deja de funcionar hasta que tenga una"
        " clave nueva."
    ),
    "In the app's Connect screen, type the server address and this key. The app cannot scan"
    " the QR code yet; it is here for a later version.": (
        "En la pantalla Conectar de la app, escribe la dirección del servidor y esta clave. La"
        " app aún no puede escanear el código QR; está aquí para una versión futura."
    ),
    "e.g. Pixel phone": "p. ej. móvil Pixel",
    "Must be https, as the app reaches it (for example the tailscale serve address). Set"
    " UT_ADMIN_PUBLIC_URL to prefill it.": (
        "Debe ser https, tal como la alcanza la app (por ejemplo, la dirección de tailscale"
        " serve). Define UT_ADMIN_PUBLIC_URL para rellenarla de antemano."
    ),
    "Filter by state": "Filtrar por estado",
    "Requested by": "Pedida por",
    "Cancel the download of %(title)s?": "¿Cancelar la descarga de %(title)s?",
    "No downloads here.": "No hay descargas.",
    "No downloads in this state.": "No hay descargas en este estado.",
    "Newest first; the list refreshes itself every 5 seconds. A download is tried up to 3"
    " times on its own; Retry queues a failed or cancelled one again with fresh attempts.": (
        "Las más recientes primero; la lista se actualiza sola cada 5 segundos. Una descarga se"
        " intenta hasta 3 veces por sí sola; Reintentar vuelve a poner en cola una fallida o"
        " cancelada con los intentos a cero."
    ),
    "Pages": "Páginas",
    "Page %(number)s": "Página %(number)s",
    "Newer": "Más recientes",
    "Older": "Más antiguas",
    "Mark reviewed": "Marcar como revisada",
    "Marked as reviewed.": "Marcada como revisada.",
    "No track needs review.": "Ninguna canción necesita revisión.",
    "MusicBrainz had no strong match for these songs, so they keep the YouTube Music tags."
    " Check them in a player: mark them reviewed to keep them as they are, or delete them (a"
    " new search fetches them again).": (
        "MusicBrainz no encontró una coincidencia clara para estas canciones, así que conservan"
        " las etiquetas de YouTube Music. Revísalas en un reproductor: márcalas como revisadas"
        " para dejarlas como están, o bórralas (una búsqueda nueva las vuelve a traer)."
    ),
    "Delete %(name)s from the library and from disk? This cannot be undone.": (
        "¿Borrar %(name)s de la biblioteca y del disco? No se puede deshacer."
    ),
    "Title or album name": "Título o nombre del álbum",
    "Only the first 200 matches are shown: refine the search.": (
        "Solo se muestran las 200 primeras coincidencias: afina la búsqueda."
    ),
    "Sign-ins, account and key changes, and every action taken in this panel, newest first."
    " Secrets are never recorded.": (
        "Inicios de sesión, cambios de cuentas y claves, y cada acción hecha en este panel, los"
        " más recientes primero. Nunca se registran secretos."
    ),
    "Filter": "Filtrar",
    "Clear": "Quitar filtros",
    "The worker updates yt-dlp by itself every day (signed releases only) and runs the"
    " canary, a test download of one fixed Creative Commons song, daily. Use these buttons"
    " after a wave of failed downloads; the next worker report (within minutes) picks the"
    " command up.": (
        "El worker actualiza yt-dlp por sí solo cada día (solo versiones firmadas) y ejecuta el"
        " canario, una descarga de prueba de una canción fija con licencia Creative Commons, a"
        " diario. Usa estos botones tras una racha de descargas fallidas; el siguiente informe"
        " del worker (en pocos minutos) recoge la orden."
    ),
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
    "UT_NOTIFY_USERNAME and UT_NOTIFY_PASSWORD, together with UT_NOTIFY_HOST (the ntfy host "
    "name), as Docker secrets or environment variables, and restart the api. They go only to "
    "that host, over https, for ntfy and webhook targets.": (
        "Para un servidor ntfy que pide inicio de sesión, define UT_NOTIFY_TOKEN (un token de"
        " acceso de ntfy), o UT_NOTIFY_USERNAME y UT_NOTIFY_PASSWORD, junto con UT_NOTIFY_HOST"
        " (el nombre del servidor ntfy), como secretos de Docker o variables de entorno, y"
        " reinicia la api. Solo se envían a ese servidor, por https, para destinos ntfy y"
        " webhook."
    ),
    "They are sent only to %(host)s (UT_NOTIFY_HOST).": (
        "Solo se envían a %(host)s (UT_NOTIFY_HOST)."
    ),
    "The URL above is not on UT_NOTIFY_HOST: notifications go there without credentials.": (
        "La URL de arriba no está en UT_NOTIFY_HOST: las notificaciones van sin credenciales."
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
    "The URL has an invalid port": "La URL tiene un puerto no válido",
    "Unknown notification kind": "Tipo de notificación desconocido",
    # Errors of T04's AuthService shown in the panel
    "That username is taken": "Ese nombre de usuario ya existe",
    "No such user": "No existe ese usuario",
    "No such key": "No existe esa clave",
    "The role must be admin or user": "El rol debe ser admin o user",
}
