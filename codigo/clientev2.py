import socket
import threading
import os
import base64

HOST = '192.168.56.10'
PORT = 55555
MAX_BYTES_ARCHIVO = 5_000_000  # 5 MB

apagando = threading.Event()
nickname = None


def negociar_nickname(cliente):
    """Envía nickname con \\n y reintenta hasta OK del servidor."""
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
            cliente.sendall((candidato + "\n").encode('utf-8'))
            respuesta = cliente.recv(4096).decode('utf-8', errors='ignore').strip()
        except OSError:
            return False
        if not respuesta:
            print("\n[cliente] El servidor cerró la conexión.")
            return False
        # Puede venir "ERROR:..." o "OK:..."
        primera = respuesta.split("\n")[0].strip()
        if primera.startswith("OK:"):
            nickname = candidato
            print(primera)
            return True
        elif primera.startswith("ERROR:"):
            print(primera + " Intenta de nuevo.")
        else:
            print(primera)
    return False


def recibir_mensajes(cliente):
    buf = bytearray()
    while not apagando.is_set():
        try:
            datos = cliente.recv(4096)
            if not datos:
                if not apagando.is_set():
                    print("\n[cliente] Servidor cerrado.")
                    apagando.set()
                break
            buf += datos
            while b"\n" in buf:
                idx = buf.index(b"\n")
                texto = bytes(buf[:idx]).decode('utf-8', errors='ignore').strip()
                del buf[:idx + 1]
                if not texto:
                    continue
                if texto.startswith('@archivo_recibido:'):
                    resto = texto[len('@archivo_recibido:'):]
                    nombre, sep, b64 = resto.partition(':')
                    nombre = os.path.basename(nombre.strip())
                    b64 = b64.strip()
                    if not sep or not nombre or not b64:
                        print("[archivo] Aviso corrupto, ignorado.")
                        continue
                    try:
                        contenido = base64.b64decode(b64.encode('ascii'), validate=True)
                    except Exception:
                        print(f"[archivo] '{nombre}' llegó corrupto, ignorado.")
                        continue
                    guardar = f"recibido_{nombre}"
                    try:
                        with open(guardar, 'wb') as f:
                            f.write(contenido)
                        print(f"[archivo guardado como {guardar} ({len(contenido)} bytes)]")
                    except OSError as e:
                        print(f"[archivo] No se pudo guardar '{nombre}': {e}")
                elif texto.startswith("OK:"):
                    continue  # resto del handshake, ignorar
                else:
                    print(texto)
        except OSError:
            break  # socket cerrado por nosotros -> salida silenciosa
        except Exception:
            if not apagando.is_set():
                print("\n[cliente] Desconectado del servidor.")
            break


def enviar_archivo(cliente, destinatario: str, ruta: str):
    destinatario = destinatario.strip()
    ruta = ruta.strip().strip('"').strip("'")
    if not destinatario or not ruta:
        print("Uso: @archivo:nickname:archivo | @archivo:todos:archivo")
        return
    if not os.path.isfile(ruta):
        print(f"El archivo {ruta} no existe")
        return
    if os.path.getsize(ruta) > MAX_BYTES_ARCHIVO:
        print("ERROR: archivo demasiado grande (máx 5 MB).")
        return
    try:
        with open(ruta, 'rb') as f:
            crudo = f.read()
        b64 = base64.b64encode(crudo).decode('ascii')
    except OSError as e:
        print(f"No se pudo leer '{ruta}': {e}")
        return
    nombre = os.path.basename(ruta)
    # Una sola línea delimitada por \\n. El base64 NO contiene \\n, así no se rompe.
    mensaje = f"@archivo:{destinatario}:{nombre}:{b64}\n"
    try:
        cliente.sendall(mensaje.encode('utf-8'))
        donde = "a todos" if destinatario.lower() == "todos" else f"a {destinatario}"
        print(f"[enviando {nombre} ({len(crudo)} bytes) {donde}...]")
    except OSError:
        if not apagando.is_set():
            print("\n[cliente] No se pudo enviar. Conexión perdida.")
        apagando.set()


def enviar_mensajes(cliente):
    print("Comandos:")
    print("  @todos: mensaje           -> chat a todos")
    print("  @nickname: mensaje        -> chat privado")
    print("  @archivo:todos:nota.txt   -> archivo a todos")
    print("  @archivo:nick:nota.txt    -> archivo privado")
    print("  mensaje                   -> chat a todos por defecto")
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

        if texto.startswith('@archivo:'):
            resto = texto[len('@archivo:'):]
            destinatario, sep, ruta = resto.partition(':')
            if not sep:
                print("Uso: @archivo:nickname:archivo | @archivo:todos:archivo")
                continue
            enviar_archivo(cliente, destinatario, ruta)
        else:
            try:
                cliente.sendall((texto + "\n").encode('utf-8'))
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
