import socket
import threading
import os
import base64
from datetime import datetime

HOST = '192.168.56.10'
PORT = 55555
MAX_BYTES_ARCHIVO = 5_000_000  # 5 MB
HISTORIAL_FILE = "historial_archivos.txt"

apagando = threading.Event()
nickname = None

candado = threading.Lock()
ofertas = {}    # id -> (emisor, nombre, tam)
historial = []  # lista de dicts: fecha, emisor, nombre, bytes, ruta


def registrar_historial(emisor: str, nombre: str, nbytes: int, ruta: str, estado: str):
    entry = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "emisor": emisor,
        "nombre": nombre,
        "bytes": nbytes,
        "ruta": ruta,
        "estado": estado,  # "aceptado" | "rechazado"
    }
    with candado:
        historial.append(entry)
    try:
        if estado == "aceptado":
            detalle = f"{nombre} | {nbytes} bytes | {ruta}"
        else:
            detalle = f"{nombre} | (no guardado)"
        with open(HISTORIAL_FILE, "a", encoding="utf-8") as f:
            f.write(f"{entry['fecha']} | de {emisor} | {detalle} | {estado.upper()}\n")
    except OSError:
        pass
    return entry


def mostrar_historial():
    with candado:
        copia = list(historial)
    if not copia:
        # Si no hay nada en sesión, mostrar lo persistido
        if os.path.isfile(HISTORIAL_FILE):
            try:
                with open(HISTORIAL_FILE, "r", encoding="utf-8") as f:
                    lineas = [l.rstrip("\n") for l in f if l.strip()]
                if not lineas:
                    print("[historial] Vacío. Aún no has recibido ni rechazado archivos.")
                    return
                print(f"[historial] Últimos {min(20, len(lineas))} registro(s):")
                for l in lineas[-20:]:
                    print(f"  - {l}")
                return
            except OSError:
                pass
        print("[historial] Vacío. Aún no has recibido ni rechazado archivos.")
        return
    print(f"[historial] Archivos de esta sesión ({len(copia)}):")
    for i, e in enumerate(copia, 1):
        estado = e.get('estado', 'aceptado')
        if estado == "rechazado":
            print(f"  {i}. {e['fecha']} | de {e['emisor']} | {e['nombre']} | RECHAZADO (no guardado)")
        else:
            print(f"  {i}. {e['fecha']} | de {e['emisor']} | {e['nombre']} | {e['bytes']} bytes | {e['ruta']} | ACEPTADO")


def borrar_historial():
    with candado:
        historial.clear()
    try:
        if os.path.isfile(HISTORIAL_FILE):
            os.remove(HISTORIAL_FILE)
        print("[historial] Historial borrado (sesión + archivo).")
    except OSError as e:
        print(f"[historial] No se pudo borrar el archivo: {e}")


def mostrar_ayuda():
    print("Comandos:")
    print("  mensaje                   -> chat a todos")
    print("  @todos: mensaje           -> chat a todos")
    print("  @nickname: mensaje        -> chat privado")
    print("  @lista                    -> ver clientes conectados")
    print("  @archivo:todos:nota.pdf   -> ofrecer archivo a todos")
    print("  @archivo:nick:nota.pdf    -> ofrecer archivo privado")
    print("  @aceptar <id>             -> aceptar archivo ofrecido")
    print("  @rechazar <id>            -> rechazar archivo ofrecido")
    print("  @historial                -> ver historial (aceptados/rechazados)")
    print("  @borrar_historial         -> borrar historial (sesión + archivo)")
    print("  @ayuda                    -> esta ayuda (local)")
    print("  (Ctrl+C para salir)")


def negociar_nickname(cliente):
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

                # --- Lista de conectados ---
                if texto.startswith("@lista_respuesta:"):
                    resto = texto[len("@lista_respuesta:"):]
                    n_txt, _, csv = resto.partition(":")
                    try:
                        n = int(n_txt.strip())
                    except ValueError:
                        n = -1
                    nombres = [x for x in csv.split(",") if x.strip()]
                    if n >= 0:
                        print(f"[lista] Conectados ({n}): {', '.join(nombres) if nombres else '(nadie más)'})")
                    else:
                        print(f"[lista] {csv}")
                    continue

                # --- Oferta de archivo: pide confirmación (SIN input aquí) ---
                if texto.startswith("@archivo_oferta:"):
                    resto = texto[len("@archivo_oferta:"):]
                    # formato id:emisor:nombre:tam
                    oid_txt, _, r2 = resto.partition(":")
                    emisor_o, _, r3 = r2.partition(":")
                    nombre_o, _, tam_txt = r3.partition(":")
                    try:
                        oid = int(oid_txt.strip())
                        tam = int(tam_txt.strip())
                    except ValueError:
                        continue
                    emisor_o = emisor_o.strip()
                    nombre_o = os.path.basename(nombre_o.strip())
                    with candado:
                        ofertas[oid] = (emisor_o, nombre_o, tam)
                    print(f"\n[archivo] '{emisor_o}' quiere enviarte '{nombre_o}' ({tam} bytes) [id={oid}]")
                    print(f"  Escribe @aceptar {oid}  para recibirlo")
                    print(f"  Escribe @rechazar {oid} para rechazarlo")
                    continue

                # --- Archivo aceptado: guardar + historial (con emisor real del servidor) ---
                if texto.startswith('@archivo_recibido:'):
                    resto = texto[len('@archivo_recibido:'):]
                    # Formato nuevo: id:emisor:nombre:b64 (con fallback al viejo nombre:b64)
                    partes = resto.split(":", 3)
                    if len(partes) == 4:
                        oid_txt, emisor_txt, nombre, b64 = partes
                        try:
                            oid = int(oid_txt.strip())
                        except ValueError:
                            oid = None
                        emisor_txt = emisor_txt.strip()
                    elif len(partes) == 2:
                        # Fallback viejo: nombre:b64
                        nombre, b64 = partes
                        oid = None
                        emisor_txt = "desconocido"
                    elif len(partes) == 3:
                        # Intermedio: emisor:nombre:b64
                        emisor_txt, nombre, b64 = partes
                        emisor_txt = emisor_txt.strip()
                        oid = None
                    else:
                        print("[archivo] Aviso corrupto, ignorado.")
                        continue
                    nombre = os.path.basename(nombre.strip())
                    b64 = b64.strip()
                    if not nombre or not b64:
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
                        registrar_historial(emisor_txt, nombre, len(contenido), guardar, "aceptado")
                        with candado:
                            if oid is not None:
                                ofertas.pop(oid, None)
                            else:
                                # Fallback: limpiar por nombre (clientes viejos)
                                for _oid, (_em, nom, _t) in list(ofertas.items()):
                                    if nom == nombre:
                                        ofertas.pop(_oid, None)
                                        break
                        print(f"[archivo guardado como {guardar} ({len(contenido)} bytes)]")
                        print("  Escribe @historial para ver tu historial.")
                    except OSError as e:
                        print(f"[archivo] No se pudo guardar '{nombre}': {e}")
                    continue

                if texto.startswith("OK:"):
                    continue
                else:
                    print(texto)
        except OSError:
            break
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
    mensaje = f"@archivo:{destinatario}:{nombre}:{b64}\n"
    try:
        cliente.sendall(mensaje.encode('utf-8'))
        donde = "a todos" if destinatario.lower() == "todos" else f"a {destinatario}"
        print(f"[ofreciendo {nombre} ({len(crudo)} bytes) {donde}... esperando confirmación]")
    except OSError:
        if not apagando.is_set():
            print("\n[cliente] No se pudo enviar. Conexión perdida.")
        apagando.set()


def enviar_mensajes(cliente):
    mostrar_ayuda()
    while not apagando.is_set():
        try:
            texto = input("")
        except (KeyboardInterrupt, EOFError):
            print("\n[cliente] Saliendo del chat... Hasta luego.")
            apagando.set()
            break
        if not texto.strip():
            continue
        t = texto.strip()

        # --- Comandos locales (no viajan al servidor) ---
        if t.lower() == "@historial":
            mostrar_historial()
            continue
        if t.lower() in ("@borrar_historial", "@limpiar_historial", "@clear_historial"):
            borrar_historial()
            continue
        if t.lower() == "@ayuda":
            mostrar_ayuda()
            continue
        if t.lower().startswith("@aceptar"):
            partes = t.split()
            if len(partes) != 2:
                print("Uso: @aceptar <id>")
                continue
            try:
                oid = int(partes[1].strip())
                cliente.sendall(f"@archivo_respuesta:{oid}:s\n".encode('utf-8'))
                # NO borramos la oferta aquí: se borra al llegar el archivo,
                # así conservamos el emisor real para el historial.
            except (ValueError, OSError):
                print("Uso: @aceptar <id>")
            continue
        if t.lower().startswith("@rechazar"):
            partes = t.split()
            if len(partes) != 2:
                print("Uso: @rechazar <id>")
                continue
            try:
                oid = int(partes[1].strip())
                with candado:
                    info = ofertas.pop(oid, None)
                if info is not None:
                    em_o, nom_o, tam_o = info
                    registrar_historial(em_o, nom_o, tam_o, "-", "rechazado")
                    print(f"[historial] Registrado rechazo de '{nom_o}' de '{em_o}'.")
                cliente.sendall(f"@archivo_respuesta:{oid}:n\n".encode('utf-8'))
            except (ValueError, OSError):
                print("Uso: @rechazar <id>")
            continue

        # --- Al servidor ---
        if t.startswith('@archivo:'):
            resto = t[len('@archivo:'):]
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
