import flet as ft
import csv
import threading
import os
import re
import time
import json
import ssl
import urllib.request
import platform # <--- Para detectar si es Windows o Android

# --- CONFIGURACIÓN ---
URL_CSV = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRX2MAGIFlkpTm_SE2kVwKt7CwPR4xhaPnWFOh5TOWdykxfT8N1QGJru4aoBD6W9R5udYGew4VyetFH/pub?gid=983288468&single=true&output=csv"
CACHE_FILE = "andromeda_db.json"

# En Android, no podemos elegir la ruta libremente.
# Usaremos una carpeta relativa simple, el sistema operativo decidirá dónde ponerla.
STORAGE_FOLDER = "Andromeda_Files" 

if not os.path.exists(STORAGE_FOLDER):
    try:
        os.makedirs(STORAGE_FOLDER)
    except:
        pass # En algunos permisos de Android esto se maneja diferente

state = {
    "data": [],
    "jerarquia": {},
    "ruta_actual": [],
    "busqueda": "",
    "syncing": False
}

def main(page: ft.Page):
    page.title = "Mnemo - Andrómeda"
    page.bgcolor = "#111111"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0
    
    # En Android esto se ignorará, pero sirve para probar en PC
    page.window_width = 400 
    page.window_height = 800

    # --- UTILIDADES ---
    def safe_str(val): return str(val).strip() if val else ""

    def extraer_id_drive(link_raw):
        link = safe_str(link_raw)
        if not link: return ""
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', link)
        return match.group(1) if match else link

    def inferir_metadatos(nombre_archivo):
        nombre = safe_str(nombre_archivo).upper()
        area = "General"
        match_area = re.search(r'-(\d{4})[-_]', nombre)
        if match_area: area = f"Área {match_area.group(1)}"
        elif "1002" in nombre: area = "Área 1002"
        
        tipo = "Doc"
        if "DW" in nombre or "PLANO" in nombre: tipo = "Plano"
        elif "TS" in nombre or "ET" in nombre: tipo = "Espec. Téc."
        elif "MC" in nombre or "MEMORIA" in nombre: tipo = "Memoria"
        
        return area, tipo

    def get_local_path(nombre_archivo):
        # Limpieza de nombre estricta
        nombre_clean = re.sub(r'[\\/*?:"<>|]', "", nombre_archivo)
        if not nombre_clean.lower().endswith(".pdf"): nombre_clean += ".pdf"
        
        # Obtenemos ruta absoluta para evitar confusiones
        return os.path.abspath(os.path.join(STORAGE_FOLDER, nombre_clean))

    def is_downloaded(nombre_archivo):
        return os.path.exists(get_local_path(nombre_archivo))

    # --- NÚCLEO DE DATOS ---
    def procesar_datos(csv_text):
        from io import StringIO
        f = StringIO(csv_text)
        reader = csv.DictReader(f, fieldnames=["col_archivo", "col_link", "col_nombre_real"])
        processed = []
        for idx, row in enumerate(reader):
            nombre = safe_str(row.get("col_archivo"))
            link = safe_str(row.get("col_link"))
            nombre_real = safe_str(row.get("col_nombre_real"))

            if not nombre or "nombre del documento" in nombre.lower(): continue
            drive_id = extraer_id_drive(link)
            if not drive_id: continue

            area, tipo = inferir_metadatos(nombre)
            titulo = nombre_real if (nombre_real and nombre_real != "#N/A") else nombre

            processed.append({
                "id": drive_id,
                "titulo": titulo,
                "nombre_archivo": nombre,
                "area": area,
                "tipo": tipo,
                "local_path": get_local_path(nombre)
            })
        return processed

    def construir_jerarquia(docs):
        jerarquia = {}
        for doc in docs:
            area = doc["area"]
            tipo = doc["tipo"]
            if area not in jerarquia: jerarquia[area] = {"_count": 0, "_sub": {}}
            if tipo not in jerarquia[area]["_sub"]: jerarquia[area]["_sub"][tipo] = {"_count": 0, "_docs": []}
            jerarquia[area]["_sub"][tipo]["_docs"].append(doc)
            jerarquia[area]["_sub"][tipo]["_count"] += 1
            jerarquia[area]["_count"] += 1
        return jerarquia

    # --- MOTOR DE SINCRONIZACIÓN ---
    def sync_total():
        if state["syncing"]: return
        state["syncing"] = True
        
        btn_sync.disabled = True
        btn_sync.text = "CONECTANDO..."
        progress_bar.visible = True
        progress_bar.value = None
        progress_text.visible = True
        progress_text.value = "Obteniendo lista..."
        page.update()

        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            response = urllib.request.urlopen(URL_CSV, context=ctx, timeout=10)
            content = response.read().decode('utf-8')
            state["data"] = procesar_datos(content)
            
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state["data"], f, ensure_ascii=False)

            total_docs = len(state["data"])
            descargados = 0
            errores = 0

            for i, doc in enumerate(state["data"]):
                progress_bar.value = (i / total_docs)
                
                if is_downloaded(doc["nombre_archivo"]):
                    msg = f"Verificando {i+1}/{total_docs}..."
                else:
                    msg = f"⬇️ Bajando {i+1}/{total_docs}..."
                    try:
                        url = f"https://drive.google.com/uc?export=download&id={doc['id']}"
                        with urllib.request.urlopen(url, context=ctx, timeout=30) as resp, open(doc["local_path"], 'wb') as f_out:
                            f_out.write(resp.read())
                        descargados += 1
                    except Exception as e:
                        print(f"Error {doc['nombre_archivo']}: {e}")
                        errores += 1
                
                # Actualizamos la UI solo cada 5 archivos para no saturar el móvil
                if i % 5 == 0:
                    progress_text.value = msg
                    page.update()

            state["jerarquia"] = construir_jerarquia(state["data"])
            msg_final = f"✅ Sync Fin. Nuevos: {descargados}. Errores: {errores}."
            
            render_contenido()
            page.snack_bar = ft.SnackBar(ft.Text(msg_final), bgcolor="green" if errores == 0 else "orange")
            page.snack_bar.open = True

        except Exception as e:
            try:
                if os.path.exists(CACHE_FILE):
                    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                        state["data"] = json.load(f)
                        state["jerarquia"] = construir_jerarquia(state["data"])
                    msg_final = "⚠️ Modo OFFLINE activado."
                    render_contenido()
                else:
                    msg_final = "❌ Sin datos y sin conexión."
            except:
                msg_final = f"Error crítico: {e}"

            page.snack_bar = ft.SnackBar(ft.Text(msg_final), bgcolor="red")
            page.snack_bar.open = True

        finally:
            state["syncing"] = False
            btn_sync.disabled = False
            btn_sync.text = "SYNC TOTAL 🔄"
            progress_bar.visible = False
            progress_text.visible = False
            page.update()

    # --- UI COMPONENTS ---
    def abrir_archivo(doc):
        path = doc["local_path"]
        if is_downloaded(doc["nombre_archivo"]):
            try:
                sistema = platform.system()
                if sistema == "Windows":
                    os.startfile(path)
                else:
                    # Lógica para ANDROID / iOS / Linux
                    # Flet intenta abrir la URL local. 
                    # Nota: En Android moderno esto puede requerir FileProvider,
                    # pero page.launch_url es el intento estándar.
                    page.launch_url(path) 
            except Exception as e:
                page.snack_bar = ft.SnackBar(ft.Text(f"Error al abrir: {e}"), bgcolor="red")
                page.snack_bar.open = True
        else:
            page.snack_bar = ft.SnackBar(ft.Text("⚠️ Archivo no descargado."), bgcolor="orange")
            page.snack_bar.open = True
        page.update()

    def crear_tarjeta(doc):
        icono = "✅" if is_downloaded(doc["nombre_archivo"]) else "☁️"
        color_icono = "green" if icono == "✅" else "grey"
        
        return ft.Container(
            padding=10, bgcolor="#1E1E1E", border_radius=5,
            content=ft.Row([
                ft.Icon(ft.icons.DESCRIPTION, color="blue"),
                ft.Column([
                    ft.Text(doc["titulo"], weight="bold", size=14, max_lines=2, overflow="ellipsis"),
                    ft.Text(f"{doc['tipo']} | {icono}", size=11, color=color_icono)
                ], expand=True),
                ft.IconButton(ft.icons.OPEN_IN_NEW, on_click=lambda e: abrir_archivo(doc))
            ])
        )

    def crear_carpeta(nombre, count, es_tipo=False):
        icon = ft.icons.FOLDER if not es_tipo else ft.icons.FOLDER_OPEN
        return ft.ListTile(
            leading=ft.Icon(icon, color="amber"),
            title=ft.Text(nombre, weight="bold"),
            subtitle=ft.Text(f"{count} items"),
            on_click=lambda e: navegar(nombre)
        )

    contenido = ft.Column(scroll="auto", expand=True)
    
    def navegar(destino):
        state["ruta_actual"].append(destino)
        render_contenido()

    def volver(e):
        if state["ruta_actual"]: state["ruta_actual"].pop()
        render_contenido()

    def render_contenido():
        contenido.controls.clear()
        if state["ruta_actual"]:
            contenido.controls.append(
                ft.Row([
                    ft.IconButton(ft.icons.ARROW_BACK, on_click=volver),
                    ft.Text(" / ".join(state["ruta_actual"]), size=16, weight="bold")
                ])
            )

        nivel = len(state["ruta_actual"])
        if not state["data"]:
            contenido.controls.append(ft.Text("Iniciando sistema...", color="grey"))
        elif nivel == 0:
            for area in sorted(state["jerarquia"].keys()):
                contenido.controls.append(crear_carpeta(area, state["jerarquia"][area]["_count"]))
        elif nivel == 1:
            area = state["ruta_actual"][0]
            tipos = state["jerarquia"][area]["_sub"]
            for tipo in sorted(tipos.keys()):
                contenido.controls.append(crear_carpeta(tipo, tipos[tipo]["_count"], True))
        elif nivel == 2:
            area, tipo = state["ruta_actual"][0], state["ruta_actual"][1]
            docs = state["jerarquia"][area]["_sub"][tipo]["_docs"]
            for doc in docs:
                contenido.controls.append(crear_tarjeta(doc))
        page.update()

    btn_sync = ft.ElevatedButton("SYNC TOTAL 🔄", bgcolor="blue", color="white", on_click=lambda e: threading.Thread(target=sync_total, daemon=True).start())
    progress_bar = ft.ProgressBar(visible=False, color="orange")
    progress_text = ft.Text("", visible=False, size=12, color="orange")

    page.add(
        ft.Container(
            padding=10, bgcolor="#222222",
            content=ft.Column([
                ft.Text("ANDRÓMEDA", size=20, weight="bold", color="white"),
                btn_sync,
                progress_bar,
                progress_text,
                ft.Divider(),
                contenido
            ], expand=True)
        )
    )
    
    # Auto-arranque
    threading.Thread(target=sync_total, daemon=True).start()

if __name__ == "__main__":
    ft.app(target=main)