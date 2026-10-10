import socket
import threading

# Configuración del servidor
HOST = '0.0.0.0'
PORT = 55555

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen()

# cliente_socket -> nickname
clientes = {}
lock = threading.Lock()


def transmitir(mensaje: bytes, cliente_origen=None):
    """Envía el mensaje a todos los clientes excepto al que lo envió."""
    with lock:
        destinos = [c for c in clientes if c != cliente_origen]
    for cliente in destinos:
        try:
            cliente.sendall(mensaje)
        except OSError:
            remover_cliente(cliente)


def remover_cliente(cliente):
    """Elimina al cliente y libera su nickname."""
    with lock:
        nickname = clientes.pop(cliente, None)
    if nickname:
        print(f"[desconexión] '{nickname}' se ha desconectado.")
        transmitir(f"[servidor] '{nickname}' salió del chat.".encode('utf-8'))
    try:
        cliente.close()
    except OSError:
        pass


def nickname_en_uso(nickname: str) -> bool:
    """Comparación case-insensitive para evitar 'Ana' vs 'ana'."""
    with lock:
        usados = {n.lower() for n in clientes.values()}
    return nickname.lower() in usados


def negociar_nickname(cliente) -> str | None:
    """
    Handshake de nickname único.
    Protocolo:
      Servidor -> "NICK" (petición)
      Cliente  -> "mi_nombre"
      Servidor -> "OK:..." (aceptado) o "ERROR:..." (rechazado, reintentar)
    Devuelve el nickname aceptado o None si el cliente se desconectó.
    """
    while True:
        try:
            cliente.sendall(b"NICK")
            datos = cliente.recv(1024)
            if not datos:
                return None
            nickname = datos.decode('utf-8', errors='ignore').strip()
        except OSError:
            return None
        except Exception:
            return None

        # Validaciones básicas
        if not nickname:
            try:
                cliente.sendall("ERROR: El nombre no puede estar vacío.".encode('utf-8'))
            except OSError:
                return None
            continue
        if len(nickname) > 20 or any(c.isspace() for c in nickname):
            try:
                cliente.sendall("ERROR: Usa 1-20 caracteres sin espacios.".encode('utf-8'))
            except OSError:
                return None
            continue
        if nickname_en_uso(nickname):
            try:
                cliente.sendall(
                    f"ERROR: El nombre '{nickname}' ya está en uso. Elige otro.".encode('utf-8')
                )
            except OSError:
                return None
            continue

        # Reservar nickname de forma atómica (evita race condition
        # si dos hilos piden el mismo nombre a la vez).
        with lock:
            if nickname.lower() in {n.lower() for n in clientes.values()}:
                try:
                    cliente.sendall(
                        f"ERROR: El nombre '{nickname}' ya está en uso. Elige otro.".encode('utf-8')
                    )
                except OSError:
                    return None
                continue
            clientes[cliente] = nickname

        try:
            cliente.sendall(f"OK: Bienvenido, {nickname}!".encode('utf-8'))
        except OSError:
            with lock:
                clientes.pop(cliente, None)
            return None
        return nickname


def manejar_cliente(cliente):
    """Hilo dedicado: negocia nickname y luego reenvía mensajes."""
    nickname = negociar_nickname(cliente)
    if nickname is None:
        try:
            cliente.close()
        except OSError:
            pass
        return

    try:
        print(f"[conexión] '{nickname}' conectado desde {cliente.getpeername()}.")
    except OSError:
        print(f"[conexión] '{nickname}' conectado.")
    transmitir(f"[servidor] '{nickname}' se unió al chat.".encode('utf-8'), cliente_origen=cliente)

    while True:
        try:
            mensaje = cliente.recv(1024)
            if not mensaje:
                break
            texto = mensaje.decode('utf-8', errors='ignore')
            transmitir(f"{nickname}: {texto}".encode('utf-8'), cliente_origen=cliente)
        except OSError:
            break  # socket cerrado al apagar -> salida silenciosa
        except Exception:
            break

    remover_cliente(cliente)


def cerrar_servidor():
    """Cierra todos los sockets sin lanzar excepciones."""
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
                # El socket se cerró en cerrar_servidor() -> apagado limpio
                break
            print(f"Nueva conexión desde {str(direccion)} (nickname pendiente...)")
            hilo = threading.Thread(target=manejar_cliente, args=(cliente,), daemon=True)
            hilo.start()
    except KeyboardInterrupt:
        # <-- Aquí se traga el Ctrl+C para que NO salga el traceback
        print("\n[servidor] Interrupción por teclado (Ctrl+C). Apagando...")
    finally:
        cerrar_servidor()
        print("[servidor] Apagado limpio. Hasta luego.")


if __name__ == "__main__":
    try:
        iniciar_servidor()
    except KeyboardInterrupt:
        print("\n[servidor] Apagado limpio. Hasta luego.")
