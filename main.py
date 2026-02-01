import flet as ft
import csv
import threading
import os
import re
import json
import ssl
import urllib.request
from io import StringIO

# --- CONFIGURACIÓN ---
URL_CSV = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRX2MAGIFlkpTm_SE2kVwKt7CwPR4xhaPnWFOh5TOWdykxfT8N1QGJru4aoBD6W9R5udYGew4VyetFH/pub?gid=983288468&single=true&output=csv"
CACHE_FILE = "andromeda_db.json"
STORAGE_FOLDER = "Andromeda_Files"

if not os.path.exists(STORAGE_FOLDER):
    try: os.makedirs(STORAGE_FOLDER)
    except: pass

class AndromedaApp:
    def __init__(self):
        self.data = []
        self.jerarquia = {}
        self.ruta_actual = []
        self.syncing = False

    def safe_str(self, val): return str(val).strip() if val else ""

    def extraer_id_drive(self, link_raw):
        link = self.safe_str(link_raw)
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', link)
        return match.group(1) if match else link

    def inferir_metadatos(self, nombre_archivo):
        nombre = self.safe_str(nombre_archivo).upper()
        area = "General"
        match_area = re.search(r'-(\d{4})[-_]', nombre)
        if match_area: area = f"Área {match_area.group(1)}"
        elif "1002" in nombre: area = "Área 1002"
        
        tipo = "Doc"
        if any(x in nombre for x in ["DW", "PLANO"]): tipo = "Plano"
        elif any(x in nombre for x in ["TS", "ET"]): tipo = "Espec. Téc."
        elif any(x in nombre for x in ["MC", "MEMORIA"]): tipo = "Memoria"
        return area, tipo

    def get_local_path(self, nombre_archivo):
        nombre_clean = re.sub(r'[\\/*?:"<>|]', "", nombre_archivo)
        if not nombre_clean.lower().endswith(".pdf"): nombre_clean += ".pdf"
        return os.path.join(STORAGE_FOLDER, nombre_clean)

    def procesar_csv(self, csv_text):
        f = StringIO(csv_text)
        reader = csv.DictReader(f, fieldnames=["col_archivo", "col_link", "col_nombre_real"])
        processed = []
        for row in reader:
            nombre = self.safe_str(row.get("col_archivo"))
            link = self.safe_str(row.get("col_link"))
            if not nombre or "nombre" in nombre.lower(): continue
            drive_id = self.extraer_id_drive(link)
            if not drive_id: continue
            area, tipo = self.inferir_metadatos(nombre)
            titulo = self.safe_str(row.get("col_nombre_real"))
            if not titulo or titulo == "#N/A": titulo = nombre
            processed.append({
                "id": drive_id,
                "titulo": titulo,
                "nombre_archivo": nombre,
                "area": area,
                "tipo": tipo,
                "path": self.get_local_path(nombre)
            })
        return processed

    def construir_jerarquia(self):
        nueva_jerarquia = {}
        for doc in self.data:
            area = doc["area"]
            tipo = doc["tipo"]
            if area not in nueva_jerarquia: nueva_jerarquia[area] = {"_count": 0, "_sub": {}}
            if tipo not in nueva_jerarquia[area]["_sub"]: nueva_jerarquia[area]["_sub"][tipo] = {"_count": 0, "_docs": []}
            nueva_jerarquia[area]["_sub"][tipo]["_docs"].append(doc)
            nueva_jerarquia[area]["_sub"][tipo]["_count"] += 1
            nueva_jerarquia[area]["_count"] += 1
        self.jerarquia = nueva_jerarquia

def main(page: ft.Page):
    app = AndromedaApp()
    page.title = "Andrómeda"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#111111"
    page.padding = 10

    lbl_status = ft.Text("Listo", size=11, color="grey")
    pb = ft.ProgressBar(width=400, color="orange", visible=False)
    lista_ui = ft.Column(scroll="auto", expand=True)

    def renderizar():
        lista_ui.controls.clear()
        if app.ruta_actual:
            lista_ui.controls.append(ft.TextButton("< Volver", on_click=volver_atras, icon=ft.icons.CHEVRON_LEFT))
            lista_ui.controls.append(ft.Text(" / ".join(app.ruta_actual), size=12, color="orange"))

        nivel = len(app.ruta_actual)
        if not app.data:
            lista_ui.controls.append(ft.Container(content=ft.Text("Presiona SYNC para cargar datos", color="grey"), padding=30))
        elif nivel == 0:
            for area in sorted(app.jerarquia.keys()):
                lista_ui.controls.append(ft.ListTile(
                    leading=ft.Icon(ft.icons.FOLDER_OPEN_ROUNDED, color="amber"),
                    title=ft.Text(area),
                    on_click=lambda e, a=area: navegar(a)
                ))
        elif nivel == 1:
            area = app.ruta_actual[0]
            for tipo in sorted(app.jerarquia[area]["_sub"].keys()):
                lista_ui.controls.append(ft.ListTile(
                    leading=ft.Icon(ft.icons.FOLDER_ROUNDED, color="blue"),
                    title=ft.Text(tipo),
                    on_click=lambda e, t=tipo: navegar(t)
                ))
        elif nivel == 2:
            area, tipo = app.ruta_actual[0], app.ruta_actual[1]
            for d in app.jerarquia[area]["_sub"][tipo]["_docs"]:
                desc = os.path.exists(d["path"])
                lista_ui.controls.append(ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.icons.INSERT_DRIVE_FILE, color="green" if desc else "grey"),
                        ft.Text(d["titulo"], size=13, expand=True),
                        ft.IconButton(ft.icons.FILE_OPEN, on_click=lambda e, doc=d: abrir_doc(doc))
                    ]),
                    padding=5, bgcolor="#1A1A1A", border_radius=5
                ))
        page.update()

    def navegar(dest): app.ruta_actual.append(dest); renderizar()
    def volver_atras(e): app.ruta_actual.pop(); renderizar()
    
    def abrir_doc(doc):
        if os.path.exists(doc["path"]): page.launch_url(f"file://{os.path.abspath(doc['path'])}")
        else: page.snack_bar = ft.SnackBar(ft.Text("Aún no descargado")); page.snack_bar.open = True; page.update()

    def iniciar_sync(e):
        if app.syncing: return
        threading.Thread(target=ejecutar_sync, daemon=True).start()

    def ejecutar_sync():
        app.syncing = True
        pb.visible = True
        page.update()
        try:
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(URL_CSV, context=ctx) as r:
                app.data = app.procesar_csv(r.read().decode('utf-8'))
                app.construir_jerarquia()
                with open(CACHE_FILE, 'w') as f: json.dump(app.data, f)
            renderizar()
            for i, d in enumerate(app.data):
                if not os.path.exists(d["path"]):
                    lbl_status.value = f"Descargando {i+1}/{len(app.data)}..."
                    pb.value = (i+1)/len(app.data)
                    page.update()
                    try:
                        url = f"https://drive.google.com/uc?export=download&id={d['id']}"
                        with urllib.request.urlopen(url, context=ctx) as res, open(d["path"], 'wb') as out:
                            out.write(res.read())
                    except: pass
            lbl_status.value = "Sincronizado ✅"
        except: lbl_status.value = "Error de conexión"
        app.syncing = False
        pb.visible = False
        renderizar()

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                app.data = json.load(f)
                app.construir_jerarquia()
        except: pass

    page.add(ft.Text("ANDRÓMEDA", size=22, weight="bold"), 
             ft.ElevatedButton("SYNC TOTAL", on_click=iniciar_sync, icon=ft.icons.SYNC),
             pb, lbl_status, ft.Divider(), lista_ui)
    renderizar()

ft.app(target=main)
