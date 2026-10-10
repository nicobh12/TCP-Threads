import socket
import threading

# Configuración del cliente
HOST = '192.168.56.10'
PORT = 55555

apagando = threading.Event()


def main():
    try:
        nickname = input("Elige tu nombre de usuario: ")
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C / Ctrl+D antes de conectar -> salir sin traceback
        print("\n[cliente] Saliendo... Hasta luego.")
        return

    cliente = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        cliente.connect((HOST, PORT))
    except ConnectionRefusedError:
        print(f"[cliente] No se pudo conectar a {HOST}:{PORT}. ¿Está el servidor arriba?")
        return
    except OSError as e:
        print(f"[cliente] Error de red: {e}")
        return

    print(f"[cliente] Conectado como '{nickname}'. Escribe y pulsa Enter. (Ctrl+C para salir)")

    def recibir_mensajes():
        """Hilo secundario: escucha de forma permanente los mensajes del servidor."""
        while not apagando.is_set():
            try:
                mensaje = cliente.recv(1024).decode('utf-8')
                if not mensaje:
                    if not apagando.is_set():
                        print("\n[cliente] El servidor cerró la conexión.")
                        apagando.set()
                    break
                print(mensaje)
            except OSError:
                # Socket cerrado por nosotros mismos -> salida silenciosa
                break
            except Exception:
                if not apagando.is_set():
                    print("\n[cliente] Ha ocurrido un error o te has desconectado del servidor.")
                break

    def enviar_mensajes():
        """Hilo principal: escucha lo que escribe el usuario y lo envía."""
        while not apagando.is_set():
            try:
                texto = input("")
            except (KeyboardInterrupt, EOFError):
                # <-- Aquí se traga el Ctrl+C para que NO salga el traceback
                print("\n[cliente] Saliendo del chat... Hasta luego.")
                apagando.set()
                break
            if not texto.strip():
                continue
            try:
                mensaje_completo = f"{nickname}: {texto}"
                cliente.sendall(mensaje_completo.encode('utf-8'))
            except OSError:
                if not apagando.is_set():
                    print("\n[cliente] No se pudo enviar. Conexión perdida.")
                apagando.set()
                break

    # Iniciar el hilo para recibir datos antes de entrar al bucle de envío
    hilo_recibir = threading.Thread(target=recibir_mensajes, daemon=True)
    hilo_recibir.start()

    # Ejecutar la función de envío en el hilo principal
    try:
        enviar_mensajes()
    except KeyboardInterrupt:
        print("\n[cliente] Saliendo del chat... Hasta luego.")
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
