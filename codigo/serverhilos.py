import socket
import threading

# Configuración del servidor
HOST = '0.0.0.0'  # Localhost
PORT = 55555

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen()

clientes = []
lock = threading.Lock()


def transmitir(mensaje, cliente_origen):
    """Envía el mensaje a todos los clientes excepto al que lo envió."""
    with lock:
        destinos = list(clientes)
    for cliente in destinos:
        if cliente != cliente_origen:
            try:
                cliente.sendall(mensaje)
            except OSError:
                remover_cliente(cliente)


def remover_cliente(cliente):
    """Elimina al cliente de la lista si se desconecta."""
    with lock:
        if cliente in clientes:
            clientes.remove(cliente)
    try:
        cliente.close()
    except OSError:
        pass


def manejar_cliente(cliente):
    """Maneja la comunicación con un cliente en un hilo dedicado."""
    while True:
        try:
            mensaje = cliente.recv(1024)
            if not mensaje:
                break
            transmitir(mensaje, cliente)
        except OSError:
            break  # socket cerrado al apagar -> salida silenciosa
        except Exception:
            break

    remover_cliente(cliente)


def cerrar_servidor():
    """Cierra todos los sockets sin lanzar excepciones."""
    with lock:
        pendientes = list(clientes)
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
            print(f"Nueva conexión desde {str(direccion)}")

            with lock:
                clientes.append(cliente)

            # daemon=True: los hilos no bloquean la salida con Ctrl+C
            hilo = threading.Thread(target=manejar_cliente, args=(cliente,), daemon=True)
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
