# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spanish catalog of the web player (`web/i18n.py`). English text → Spanish text."""

ES: dict[str, str] = {
    "%(count)s songs": "%(count)s canciones",
    "Add to a playlist": "Añadir a una lista",
    "Add to favourites": "Añadir a favoritos",
    "Albums": "Álbumes",
    "Artists": "Artistas",
    "Artists, albums, songs": "Artistas, álbumes, canciones",
    "Back to Listen Now": "Volver a Escuchar",
    "Clear": "Vaciar",
    "Close": "Cerrar",
    "Delete playlist": "Borrar la lista",
    "Favourites": "Favoritos",
    "Fetching from YouTube Music…": "Obteniendo de YouTube Music…",
    "Go to album": "Ir al álbum",
    "Go to artist": "Ir al artista",
    "Library": "Biblioteca",
    "Listen Now": "Escuchar",
    "Lyrics": "Letra",
    "More": "Más",
    "New": "Nueva",
    "New playlist": "Nueva lista",
    "New playlist name": "Nombre de la nueva lista",
    "Next": "Siguiente",
    "Next page": "Página siguiente",
    "No albums yet.": "Todavía no hay álbumes.",
    "No albums.": "Sin álbumes.",
    "No artists yet.": "Todavía no hay artistas.",
    "No lyrics for this song.": "No hay letra para esta canción.",
    "No playlists yet.": "Todavía no hay listas.",
    "No results for “%(query)s”.": "No hay resultados para «%(query)s».",
    "Not in your library yet: the first play fetches it": (
        "Aún no está en tu biblioteca: la primera reproducción la descarga"
    ),
    "Not playing": "Sin reproducción",
    "Nothing in your favourites yet: tap the heart on a song, an album or an artist.": (
        "Aún no tienes favoritos: pulsa el corazón de una canción, un álbum o un artista."
    ),
    "Password": "Contraseña",  # nosec B105 - a UI label, not a secret
    "Play": "Reproducir",
    "Play later": "Reproducir después",
    "Play next": "Reproducir a continuación",
    "Play or pause": "Reproducir o pausar",
    "Player": "Reproductor",
    "Playlists": "Listas",
    "Position": "Posición",
    "Previous": "Anterior",
    "Previous page": "Página anterior",
    "Recently added": "Añadido recientemente",
    "Recently played": "Escuchado recientemente",
    "Remove": "Quitar",
    "Remove from favourites": "Quitar de favoritos",
    "Remove from this playlist": "Quitar de esta lista",
    "Search": "Buscar",
    "Search your library and YouTube Music. Songs that are not in your library yet are fetched"
    " the first time you play them.": (
        "Busca en tu biblioteca y en YouTube Music. Las canciones que aún no están en tu"
        " biblioteca se descargan la primera vez que las reproduces."
    ),
    "Sections": "Secciones",
    "Shuffle": "Aleatorio",
    "Sign in": "Entrar",
    "Sign in with your account to listen in the browser.": (
        "Entra con tu cuenta para escuchar en el navegador."
    ),
    "Sign out": "Salir",
    "Something went wrong": "Algo ha fallado",
    "Songs": "Canciones",
    "Start radio": "Crear emisora",
    "Starting radio…": "Creando la emisora…",
    "The queue is empty.": "La cola está vacía.",
    "This playlist is empty. Add songs from their menu (···).": (
        "Esta lista está vacía. Añade canciones desde su menú (···)."
    ),
    "This song cannot be played right now.": "Esta canción no se puede reproducir ahora.",
    "This song could not be fetched.": "No se pudo obtener esta canción.",
    "Up next": "A continuación",
    "Username": "Usuario",
    "Volume": "Volumen",
    "Waiting for a download slot…": "Esperando turno de descarga…",
    "Your library is empty. Search for music to start.": (
        "Tu biblioteca está vacía. Busca música para empezar."
    ),
    "Admin panel": "Panel de administración",
    "UltimateTunes server is running.": "El servidor de UltimateTunes está funcionando.",
    "Version %(version)s": "Versión %(version)s",
    # Messages of the code (`routes.MESSAGES`).
    "Your session has ended. Sign in again.": "Tu sesión ha terminado. Vuelve a entrar.",
    "The form expired or came from another site. Reload and retry.": (
        "El formulario caducó o vino de otro sitio. Recarga y vuelve a intentarlo."
    ),
    "Wrong username or password.": "Usuario o contraseña incorrectos.",
    "Too many attempts. Wait and try again.": "Demasiados intentos. Espera y vuelve a probar.",
}
