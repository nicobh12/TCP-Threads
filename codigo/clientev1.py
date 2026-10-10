import socket
import threading

HOST = '192.168.56.10'
PORT = 55555

apagando = threading.Event()
nickname = None


def negociar_nickname(cliente):
    """Envía nickname y reintenta hasta que el servidor responda OK."""
    global nickname
    while not apagando.is_set():
        try:
            candidato = input("Elige tu nombre de usuario (sin espacios): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[cliente] Saliendo... Hasta luego.")
            apagando.set()
            return False
        if not candidato:
            print("ERROR: El nombre no puede estar vacío. Intenta de nuevo.")
            continue
        try:
            cliente.sendall(candidato.encode('utf-8'))
            respuesta = cliente.recv(1024).decode('utf-8', errors='ignore')
        except OSError:
            return False
        if not respuesta:
            print("\n[cliente] El servidor cerró la conexión.")
            return False
        if respuesta.startswith("OK:"):
            nickname = candidato
            print(respuesta.strip())
            return True
        elif respuesta.startswith("ERROR:"):
            # Nombre duplicado o inválido -> el servidor lo dice, reintentamos
            print(respuesta.strip() + " Intenta de nuevo.")
        else:
            print(respuesta.strip())
    return False


def recibir_mensajes(cliente):
    while not apagando.is_set():
        try:
            mensaje = cliente.recv(1024).decode('utf-8', errors='ignore')
            if not mensaje:
                if not apagando.is_set():
                    print("\n[cliente] Servidor cerrado.")
                    apagando.set()
                break
            # Durante el handshake ya se consumieron OK/ERROR; aquí es chat.
            # Por si se cuela alguno, no lo mostramos como chat:
            if mensaje.startswith("OK:"):
                continue
            print(mensaje, end="" if mensaje.endswith("\n") else "\n")
        except OSError:
            break  # socket cerrado por nosotros -> salida silenciosa
        except Exception:
            if not apagando.is_set():
                print("\n[cliente] Desconectado del servidor.")
            break


def enviar_mensajes(cliente):
    print("Comandos:")
    print("  @todos: mensaje    -> envía a todos")
    print("  @nickname: mensaje -> envía a uno solo")
    print("  mensaje            -> envía a todos por defecto")
    print("  (Ctrl+C para salir)")
    while not apagando.is_set():
        try:
            texto = input("")
        except (KeyboardInterrupt, EOFError):
            print("\n[cliente] Saliendo del chat... Hasta luego.")
            apagando.set()
            break
        if not texto.strip():
            continue
        try:
            cliente.sendall(texto.encode('utf-8'))
        except OSError:
            if not apagando.is_set():
                print("\n[cliente] No se pudo enviar. Conexión perdida.")
            apagando.set()
            break


def main():
    cliente = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        cliente.connect((HOST, PORT))
    except ConnectionRefusedError:
        print(f"[cliente] No se pudo conectar a {HOST}:{PORT}. ¿Está el servidor arriba?")
        return
    except OSError as e:
        print(f"[cliente] Error de red: {e}")
        return

    try:
        if not negociar_nickname(cliente):
            return

        hilo_recibir = threading.Thread(target=recibir_mensajes, args=(cliente,), daemon=True)
        hilo_recibir.start()

        try:
            enviar_mensajes(cliente)
        except KeyboardInterrupt:
            print("\n[cliente] Saliendo del chat... Hasta luego.")
            apagando.set()
    except KeyboardInterrupt:
        print("\n[cliente] Saliendo... Hasta luego.")
        apagando.set()
    finally:
        apagando.set()
        try:
            cliente.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            cliente.close()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[cliente] Saliendo... Hasta luego.")
