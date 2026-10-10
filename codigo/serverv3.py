import socket
import threading
import os
import base64

HOST = '0.0.0.0'
PORT = 55555
MAX_ARCHIVO_B64 = 7_000_000  # ~5 MB binarios en base64

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen()

clientes = {}  # {socket: nickname}
lock = threading.RLock()

# Ofertas de archivo pendientes de confirmación: id -> dict
pendientes = {}
siguiente_id = 1


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
    """Chat privado."""
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
            _enviar_linea(emisor, f"ERROR: usuario '{nickname_destino}' no existe o no está conectado. Usa @lista.")
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


def enviar_lista(emisor):
    with lock:
        nombres = sorted(clientes.values())
    try:
        # Formato máquina + humano: el cliente lo formatea bonito
        _enviar_linea(emisor, f"@lista_respuesta:{len(nombres)}:{','.join(nombres)}")
    except OSError:
        pass


def _tamano_real(b64: str) -> int:
    try:
        # 4 chars b64 ~= 3 bytes
        return len(b64) * 3 // 4
    except Exception:
        return 0


def ofrecer_archivo(nickname_destino, nombre_archivo, b64, emisor):
    """Guarda el archivo y solo manda OFERTA. El contenido viaja tras el 'sí'."""
    global siguiente_id
    nombre = obtener_nick(emisor)
    if nombre is None:
        return
    nombre_archivo = os.path.basename(nombre_archivo.strip()).replace(":", "_").replace("\n", "_")
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
    # Validar que sea base64 válido (barato: solo intenta decodificar cabecera)
    try:
        base64.b64decode(b64[:64].encode('ascii'), validate=False)
    except Exception:
        try:
            _enviar_linea(emisor, "ERROR: archivo corrupto (base64 inválido).")
        except OSError:
            pass
        return

    tam = _tamano_real(b64)

    if nickname_destino.lower() == "todos":
        with lock:
            destinatarios = [(s, n) for s, n in clientes.items() if s != emisor]
        if not destinatarios:
            try:
                _enviar_linea(emisor, "ERROR: no hay otros usuarios conectados.")
            except OSError:
                pass
            return
        ids = []
        with lock:
            for sock, _nick in destinatarios:
                oid = siguiente_id
                siguiente_id += 1
                pendientes[oid] = {
                    "emisor": emisor,
                    "emisor_nombre": nombre,
                    "destino": sock,
                    "nombre_archivo": nombre_archivo,
                    "b64": b64,
                }
                ids.append((oid, sock))
        for oid, sock in ids:
            try:
                _enviar_linea(sock, f"@archivo_oferta:{oid}:{nombre}:{nombre_archivo}:{tam}")
            except OSError:
                remover_cliente(sock)
        try:
            _enviar_linea(emisor, f"[archivo -> todos] '{nombre_archivo}' ofrecido a {len(ids)} usuario(s). Esperando confirmación...")
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
            _enviar_linea(emisor, f"ERROR: usuario '{nickname_destino}' no existe o no está conectado. Usa @lista.")
        except OSError:
            pass
        return
    if destino_sock == emisor:
        try:
            _enviar_linea(emisor, "ERROR: no puedes enviarte un archivo a ti mismo (usa otra sesión para probar).")
        except OSError:
            pass
        return
    with lock:
        oid = siguiente_id
        siguiente_id += 1
        pendientes[oid] = {
            "emisor": emisor,
            "emisor_nombre": nombre,
            "destino": destino_sock,
            "nombre_archivo": nombre_archivo,
            "b64": b64,
        }
    try:
        _enviar_linea(destino_sock, f"@archivo_oferta:{oid}:{nombre}:{nombre_archivo}:{tam}")
    except OSError:
        remover_cliente(destino_sock)
        return
    try:
        _enviar_linea(emisor, f"[archivo -> {nombre_real}] '{nombre_archivo}' ofrecido. Esperando confirmación (id={oid})...")
    except OSError:
        pass


def responder_archivo(emisor, oid: int, acepta: bool):
    with lock:
        info = pendientes.get(oid)
    if info is None:
        try:
            _enviar_linea(emisor, f"ERROR: oferta id={oid} no existe o ya expiró.")
        except OSError:
            pass
        return
    # Solo el destinatario puede responder
    if info["destino"] is not emisor:
        try:
            _enviar_linea(emisor, "ERROR: esa oferta no es para ti.")
        except OSError:
            pass
        return
    with lock:
        pendientes.pop(oid, None)

    nombre_archivo = info["nombre_archivo"]
    b64 = info["b64"]
    emisor_orig = info["emisor"]
    emisor_nombre = info["emisor_nombre"]
    quien = obtener_nick(emisor) or "alguien"

    if acepta:
        try:
            _enviar_linea(emisor, f"[archivo] {emisor_nombre} te envió {nombre_archivo}")
            _enviar_linea(emisor, f"@archivo_recibido:{oid}:{emisor_nombre}:{nombre_archivo}:{b64}")
        except OSError:
            remover_cliente(emisor)
        try:
            _enviar_linea(emisor_orig, f"[servidor] '{quien}' ACEPTÓ tu archivo '{nombre_archivo}'.")
        except OSError:
            pass
    else:
        try:
            _enviar_linea(emisor, f"[servidor] Rechazaste '{nombre_archivo}' de '{emisor_nombre}'.")
        except OSError:
            pass
        try:
            _enviar_linea(emisor_orig, f"[servidor] '{quien}' RECHAZÓ tu archivo '{nombre_archivo}'.")
        except OSError:
            pass


def remover_cliente(cliente):
    with lock:
        nick = clientes.pop(cliente, None)
        # Limpiar ofertas donde participa (para no dejar basura en memoria)
        ids_borrar = [oid for oid, p in pendientes.items()
                      if p["emisor"] is cliente or p["destino"] is cliente]
        for oid in ids_borrar:
            pendientes.pop(oid, None)
    if nick:
        print(f"{nick} desconectado")
        difundir_servidor(f"[servidor] '{nick}' salió del chat.")
    try:
        cliente.close()
    except OSError:
        pass


def procesar_mensaje(texto, emisor):
    t = texto.strip()
    # --- @lista ---
    if t.lower() == "@lista":
        enviar_lista(emisor)
        return

    # --- Respuesta a oferta: @archivo_respuesta:<id>:s|n ---
    if t.lower().startswith("@archivo_respuesta:"):
        resto = t[len("@archivo_respuesta:"):].strip()
        oid_txt, sep, resp = resto.partition(":")
        oid_txt = oid_txt.strip()
        resp = resp.strip().lower()
        if not sep or not oid_txt or resp not in ("s", "si", "sí", "y", "yes", "n", "no"):
            try:
                _enviar_linea(emisor, "Uso: @aceptar <id> | @rechazar <id>")
            except OSError:
                pass
            return
        try:
            oid = int(oid_txt)
        except ValueError:
            try:
                _enviar_linea(emisor, "ERROR: id de oferta inválido.")
            except OSError:
                pass
            return
        responder_archivo(emisor, oid, acepta=resp in ("s", "si", "sí", "y", "yes"))
        return

    # --- Ofrecer archivo: @archivo:dest:nombre:b64 ---
    if t.startswith('@archivo:'):
        resto = t[len('@archivo:'):]
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
        ofrecer_archivo(destinatario, nombre, b64, emisor)
        return

    # --- Chat normal / privado ---
    if t.startswith('@'):
        cuerpo = t[1:].strip()
        if not cuerpo:
            try:
                _enviar_linea(emisor, "Uso: @todos: mensaje | @nickname: mensaje | @lista")
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
                _enviar_linea(emisor, "Uso: @todos: mensaje | @nickname: mensaje | @lista")
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
    while b"\n" not in buf:
        try:
            datos = sock.recv(4096)
        except OSError:
            return None
        if not datos:
            return None
        buf += datos
    idx = buf.index(b"\n")
    linea = bytes(buf[:idx]).decode('utf-8', errors='ignore').strip()
    del buf[:idx + 1]
    return linea


def manejar_cliente(cliente, direccion):
    buf = bytearray()
    try:
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

        while True:
            linea = _leer_linea(cliente, buf)
            if linea is None:
                break
            if linea:
                procesar_mensaje(linea, cliente)
    finally:
        remover_cliente(cliente)


def cerrar_servidor():
    with lock:
        pendientes_cli = list(clientes.keys())
    for c in pendientes_cli:
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
