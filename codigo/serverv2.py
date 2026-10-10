import socket
import threading
import os

HOST = '0.0.0.0'
PORT = 55555
MAX_ARCHIVO_B64 = 7_000_000  # ~5 MB binarios en base64

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen()

clientes = {}  # {socket: nickname}
lock = threading.Lock()


def obtener_nick(sock):
    with lock:
        return clientes.get(sock)


def nickname_valido(nickname: str) -> str | None:
    if not nickname:
        return "El nombre no puede estar vacío."
    if len(nickname) > 20:
        return "Usa 1-20 caracteres."
    if any(c.isspace() for c in nickname):
        return "Sin espacios."
    if nickname.startswith("@") or ":" in nickname:
        return "Sin '@' ni ':' (se usan para comandos)."
    if nickname.lower() == "todos":
        return "Ese nombre está reservado."
    return None


def _enviar_linea(sock, texto: str):
    sock.sendall((texto + "\n").encode('utf-8'))


def difundir_servidor(contenido: str):
    with lock:
        destinatarios = list(clientes.keys())
    mensaje = (contenido + "\n").encode('utf-8')
    for sock in destinatarios:
        try:
            sock.sendall(mensaje)
        except OSError:
            remover_cliente(sock)


def transmitir_a_todos(contenido, emisor):
    nombre = obtener_nick(emisor)
    if nombre is None or not contenido:
        return
    with lock:
        destinatarios = [s for s in clientes if s != emisor]
    mensaje = f"{nombre}: {contenido}\n".encode('utf-8')
    for sock in destinatarios:
        try:
            sock.sendall(mensaje)
        except OSError:
            remover_cliente(sock)


def transmitir_a_uno(nickname_destino, contenido, emisor):
    """Chat privado. Contenido ya viene sin prefijo."""
    nombre = obtener_nick(emisor)
    if nombre is None or not contenido:
        return
    destino_sock = None
    nombre_real_destino = None
    with lock:
        for sock, nick in clientes.items():
            if nick.lower() == nickname_destino.lower():
                destino_sock = sock
                nombre_real_destino = nick
                break
    if destino_sock is None:
        try:
            _enviar_linea(emisor, f"ERROR: usuario '{nickname_destino}' no existe o no está conectado.")
        except OSError:
            pass
        return
    if destino_sock == emisor:
        try:
            _enviar_linea(emisor, "ERROR: no puedes enviarte un privado a ti mismo.")
        except OSError:
            pass
        return
    try:
        _enviar_linea(destino_sock, f"[privado] {nombre}: {contenido}")
    except OSError:
        remover_cliente(destino_sock)
        return
    try:
        _enviar_linea(emisor, f"[privado -> {nombre_real_destino}] {nombre}: {contenido}")
    except OSError:
        pass


def transmitir_archivo(nickname_destino, nombre_archivo, b64, emisor):
    """Manda un archivo (ya en base64) a uno o a todos."""
    nombre = obtener_nick(emisor)
    if nombre is None:
        return
    nombre_archivo = os.path.basename(nombre_archivo.strip())
    if not nombre_archivo or not b64:
        try:
            _enviar_linea(emisor, "Uso: @archivo:nickname:archivo | @archivo:todos:archivo")
        except OSError:
            pass
        return
    if len(b64) > MAX_ARCHIVO_B64:
        try:
            _enviar_linea(emisor, "ERROR: archivo demasiado grande (máx ~5 MB).")
        except OSError:
            pass
        return

    info = f"[archivo] {nombre} te envió {nombre_archivo} ({len(b64)} chars b64)"
    linea_archivo = f"@archivo_recibido:{nombre_archivo}:{b64}"

    if nickname_destino.lower() == "todos":
        with lock:
            destinatarios = [s for s in clientes if s != emisor]
        for sock in destinatarios:
            try:
                _enviar_linea(sock, info)
                _enviar_linea(sock, linea_archivo)
            except OSError:
                remover_cliente(sock)
        try:
            _enviar_linea(emisor, f"[archivo -> todos] enviaste {nombre_archivo}")
        except OSError:
            pass
        return

    destino_sock = None
    nombre_real = None
    with lock:
        for sock, nick in clientes.items():
            if nick.lower() == nickname_destino.lower():
                destino_sock = sock
                nombre_real = nick
                break
    if destino_sock is None:
        try:
            _enviar_linea(emisor, f"ERROR: usuario '{nickname_destino}' no existe o no está conectado.")
        except OSError:
            pass
        return
    if destino_sock == emisor:
        try:
            _enviar_linea(emisor, "ERROR: no puedes enviarte un archivo a ti mismo (usa otra sesión para probar).")
        except OSError:
            pass
        return
    try:
        _enviar_linea(destino_sock, info)
        _enviar_linea(destino_sock, linea_archivo)
    except OSError:
        remover_cliente(destino_sock)
        return
    try:
        _enviar_linea(emisor, f"[archivo -> {nombre_real}] enviaste {nombre_archivo}")
    except OSError:
        pass


def remover_cliente(cliente):
    with lock:
        nick = clientes.pop(cliente, None)
    if nick:
        print(f"{nick} desconectado")
        difundir_servidor(f"[servidor] '{nick}' salió del chat.")
    try:
        cliente.close()
    except OSError:
        pass


def procesar_mensaje(texto, emisor):
    # --- Archivo: @archivo:destinatario:nombre_b64... (el contenido ya viene en base64) ---
    if texto.startswith('@archivo:'):
        resto = texto[len('@archivo:'):]
        destinatario, sep, resto2 = resto.partition(':')
        destinatario = destinatario.strip()
        if not sep or not destinatario:
            try:
                _enviar_linea(emisor, "Uso: @archivo:nickname:archivo | @archivo:todos:archivo")
            except OSError:
                pass
            return
        nombre, sep2, b64 = resto2.partition(':')
        nombre = nombre.strip()
        b64 = b64.strip()
        if not sep2 or not nombre or not b64:
            try:
                _enviar_linea(emisor, "Uso: @archivo:nickname:archivo | @archivo:todos:archivo")
            except OSError:
                pass
            return
        transmitir_archivo(destinatario, nombre, b64, emisor)
        return

    # --- Chat normal / privado ---
    if texto.startswith('@'):
        cuerpo = texto[1:].strip()
        if not cuerpo:
            try:
                _enviar_linea(emisor, "Uso: @todos: mensaje | @nickname: mensaje")
            except OSError:
                pass
            return
        if ':' in cuerpo:
            destinatario, _, contenido = cuerpo.partition(':')
        else:
            destinatario, _, contenido = cuerpo.partition(' ')
        destinatario = destinatario.strip()
        contenido = contenido.strip()
        if not destinatario or not contenido:
            try:
                _enviar_linea(emisor, "Uso: @todos: mensaje | @nickname: mensaje")
            except OSError:
                pass
            return
        if destinatario.lower() == 'todos':
            transmitir_a_todos(contenido, emisor)
        else:
            transmitir_a_uno(destinatario, contenido, emisor)
    else:
        transmitir_a_todos(texto, emisor)


def _leer_linea(sock, buf: bytearray) -> str | None:
    """Lee hasta \\n usando el buffer. None si se cerró."""
    while b"\n" not in buf:
        try:
            datos = sock.recv(4096)
        except OSError:
            return None
        if not datos:
            return None
        buf += datos
    linea, _, resto = buf.partition(b"\n")
    del buf[:len(linea) + 1]
    _ = resto  # partition sobre bytearray no crea resto separado; ya mutamos buf
    return linea.decode('utf-8', errors='ignore').strip()


def manejar_cliente(cliente, direccion):
    buf = bytearray()
    try:
        # --- Fase 1: nickname único (reintenta sin desconectar) ---
        nickname = None
        while True:
            linea = _leer_linea(cliente, buf)
            if linea is None:
                try:
                    cliente.close()
                except OSError:
                    pass
                return
            err = nickname_valido(linea)
            if err:
                try:
                    _enviar_linea(cliente, f"ERROR: {err}")
                except OSError:
                    return
                continue
            with lock:
                if linea.lower() in {n.lower() for n in clientes.values()}:
                    try:
                        _enviar_linea(cliente, f"ERROR: El nombre '{linea}' ya está en uso. Elige otro.")
                    except OSError:
                        return
                    continue
                clientes[cliente] = linea
                nickname = linea
            try:
                _enviar_linea(cliente, f"OK: Bienvenido {nickname}")
            except OSError:
                with lock:
                    clientes.pop(cliente, None)
                return
            break

        print(f"{nickname} conectado desde {direccion}")
        difundir_servidor(f"[servidor] '{nickname}' se unió al chat.")

        # --- Fase 2: chat + archivos, delimitado por \\n ---
        while True:
            # Reutiliza lo que ya quedó en buf (pipelining)
            if b"\n" in buf:
                linea = buf.split(b"\n", 1)[0].decode('utf-8', errors='ignore').strip()
                del buf[:len(buf.split(b"\n", 1)[0]) + 1]
                if linea:
                    procesar_mensaje(linea, cliente)
                continue
            try:
                datos = cliente.recv(4096)
            except OSError:
                break
            if not datos:
                break
            buf += datos
            while b"\n" in buf:
                crudo, _, _ = buf.partition(b"\n")
                linea = bytes(crudo).decode('utf-8', errors='ignore').strip()
                del buf[:len(crudo) + 1]
                if linea:
                    procesar_mensaje(linea, cliente)
    finally:
        remover_cliente(cliente)


def cerrar_servidor():
    with lock:
        pendientes = list(clientes.keys())
    for c in pendientes:
        try:
            c.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            c.close()
        except OSError:
            pass
    try:
        server.close()
    except OSError:
        pass


def iniciar_servidor():
    print(f"Servidor ejecutándose en {HOST}:{PORT}... (Ctrl+C para detener)")
    try:
        while True:
            try:
                cliente, direccion = server.accept()
            except OSError:
                break
            hilo = threading.Thread(target=manejar_cliente, args=(cliente, direccion), daemon=True)
            hilo.start()
    except KeyboardInterrupt:
        print("\n[servidor] Interrupción por teclado (Ctrl+C). Apagando...")
    finally:
        cerrar_servidor()
        print("[servidor] Apagado limpio. Hasta luego.")


if __name__ == "__main__":
    try:
        iniciar_servidor()
    except KeyboardInterrupt:
        print("\n[servidor] Apagado limpio. Hasta luego.")
