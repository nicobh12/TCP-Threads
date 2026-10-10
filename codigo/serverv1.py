import socket
import threading

HOST = '0.0.0.0'
PORT = 55555

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen()

clientes = {}   # {socket: nickname}
lock = threading.Lock()


def obtener_nick(sock):
    with lock:
        return clientes.get(sock)


def nickname_en_uso(nickname: str) -> bool:
    with lock:
        usados = {n.lower() for n in clientes.values()}
    return nickname.lower() in usados


def nickname_valido(nickname: str) -> str | None:
    """Devuelve mensaje de error si no es válido, None si pasa el formato."""
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
    nombre = obtener_nick(emisor)
    if nombre is None or not contenido:
        return
    destino_sock = None
    with lock:
        for sock, nick in clientes.items():
            if nick.lower() == nickname_destino.lower():
                destino_sock = sock
                break
    if destino_sock is None:
        try:
            emisor.sendall(f"ERROR: usuario '{nickname_destino}' no existe o no está conectado.\n".encode('utf-8'))
        except OSError:
            pass
        return
    if destino_sock == emisor:
        try:
            emisor.sendall("ERROR: no puedes enviarte un privado a ti mismo.\n".encode('utf-8'))
        except OSError:
            pass
        return
    try:
        destino_sock.sendall(f"[privado] {nombre}: {contenido}\n".encode('utf-8'))
    except OSError:
        remover_cliente(destino_sock)
        return
    # Confirmación al emisor (para saber que sí se envió)
    try:
        emisor.sendall(f"[privado -> {nickname_destino}] {nombre}: {contenido}\n".encode('utf-8'))
    except OSError:
        pass


def remover_cliente(cliente):
    with lock:
        nick = clientes.pop(cliente, None)
    if nick:
        print(f"{nick} desconectado")
        transmitir_a_todos(f"[servidor] '{nick}' salió del chat.", emisor=_servidor_fantasma())
    try:
        cliente.close()
    except OSError:
        pass


class _Fantasma:
    """Emisor ficticio para mensajes del servidor (nunca está en clientes)."""
    pass


_FANTASMA = _Fantasma()


def _servidor_fantasma():
    return _FANTASMA


# Parche: transmitir_a_todos espera un emisor con nick; si es el fantasma usa "[servidor]"
_orig_transmitir = transmitir_a_todos


def transmitir_a_todos(contenido, emisor):  # noqa: F811 - redefinición intencional
    if emisor is _FANTASMA:
        with lock:
            destinatarios = list(clientes.keys())
        mensaje = f"{contenido}\n".encode('utf-8')
        for sock in destinatarios:
            try:
                sock.sendall(mensaje)
            except OSError:
                remover_cliente(sock)
        return
    return _orig_transmitir(contenido, emisor)


def procesar_mensaje(mensaje, emisor):
    texto = mensaje.decode('utf-8', errors='ignore').strip()
    if not texto:
        return
    if texto.startswith('@'):
        cuerpo = texto[1:].strip()
        if not cuerpo:
            try:
                emisor.sendall("Uso: @todos: mensaje | @nickname: mensaje\n".encode('utf-8'))
            except OSError:
                pass
            return
        # Acepta "@nick: mensaje" y "@nick mensaje"
        if ':' in cuerpo:
            destinatario, _, contenido = cuerpo.partition(':')
        else:
            destinatario, _, contenido = cuerpo.partition(' ')
        destinatario = destinatario.strip()
        contenido = contenido.strip()
        if not destinatario or not contenido:
            try:
                emisor.sendall("Uso: @todos: mensaje | @nickname: mensaje\n".encode('utf-8'))
            except OSError:
                pass
            return
        if destinatario.lower() == 'todos':
            transmitir_a_todos(contenido, emisor)
        else:
            transmitir_a_uno(destinatario, contenido, emisor)
    else:
        transmitir_a_todos(texto, emisor)


def negociar_nickname(cliente) -> str | None:
    """Lee el primer mensaje como nickname hasta que sea único y válido."""
    while True:
        try:
            datos = cliente.recv(1024)
            if not datos:
                return None
            nickname = datos.decode('utf-8', errors='ignore').strip()
        except OSError:
            return None

        err = nickname_valido(nickname)
        if err:
            try:
                cliente.sendall(f"ERROR: {err}\n".encode('utf-8'))
            except OSError:
                return None
            continue

        with lock:
            if nickname.lower() in {n.lower() for n in clientes.values()}:
                try:
                    cliente.sendall(f"ERROR: El nombre '{nickname}' ya está en uso. Elige otro.\n".encode('utf-8'))
                except OSError:
                    return None
                continue
            clientes[cliente] = nickname

        try:
            cliente.sendall(f"OK: Bienvenido {nickname}\n".encode('utf-8'))
        except OSError:
            with lock:
                clientes.pop(cliente, None)
            return None
        return nickname


def manejar_cliente(cliente, direccion):
    nickname = negociar_nickname(cliente)
    if nickname is None:
        try:
            cliente.close()
        except OSError:
            pass
        return

    print(f"{nickname} conectado desde {direccion}")
    transmitir_a_todos(f"[servidor] '{nickname}' se unió al chat.", emisor=_servidor_fantasma())

    try:
        while True:
            try:
                mensaje = cliente.recv(1024)
            except OSError:
                break  # socket cerrado al apagar -> salida silenciosa
            if not mensaje:
                break
            procesar_mensaje(mensaje, cliente)
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
