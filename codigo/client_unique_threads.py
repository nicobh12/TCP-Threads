import socket
import threading

# Configuración del cliente
HOST = '192.168.56.10' 
PORT = 55555

apagando = threading.Event()
nickname = None


def negociar_nickname(cliente):
    """
    Responde al handshake del servidor hasta que el nickname sea único.
    Protocolo: espera "NICK", envía candidato, espera "OK" o "ERROR".
    Devuelve True si se registró, False si el usuario canceló (Ctrl+C).
    """
    global nickname
    candidato = ""
    while not apagando.is_set():
        try:
            peticion = cliente.recv(1024).decode('utf-8', errors='ignore')
        except OSError:
            return False
        if not peticion:
            if not apagando.is_set():
                print("\n[cliente] El servidor cerró la conexión.")
            return False
        if peticion == "NICK":
            try:
                candidato = input("Elige tu nombre de usuario (sin espacios): ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n[cliente] Saliendo... Hasta luego.")
                apagando.set()
                return False
            try:
                cliente.sendall(candidato.encode('utf-8'))
            except OSError:
                return False
        elif peticion.startswith("OK:"):
            nickname = candidato
            print(peticion[3:].strip())
            return True
        elif peticion.startswith("ERROR:"):
            print(peticion[6:].strip() + " Intenta de nuevo.")
        else:
            print(peticion)
    return False


def recibir_mensajes(cliente):
    """Hilo secundario: escucha de forma permanente los mensajes del servidor."""
    while not apagando.is_set():
        try:
            mensaje = cliente.recv(1024).decode('utf-8', errors='ignore')
            if not mensaje:
                if not apagando.is_set():
                    print("\n[cliente] Desconectado del servidor.")
                    apagando.set()
                break
            if mensaje in ("NICK",) or mensaje.startswith(("OK:", "ERROR:")):
                continue
            print(mensaje)
        except OSError:
            # Socket cerrado por nosotros mismos -> salida silenciosa
            break
        except Exception:
            if not apagando.is_set():
                print("\n[cliente] Ha ocurrido un error o te has desconectado del servidor.")
            break


def enviar_mensajes(cliente):
    """Hilo principal: lee lo que escribe el usuario y lo envía (sin prefijo)."""
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
