from fastapi import FastAPI
from pydantic import BaseModel # Estructuras de datos con validacion automatica
from typing import Dict, List
from fastapi import HTTPException # Codigos HTTP por errores
import requests # Peticiones HTTP entre nodos
import os # Leer env

# --- Configuración simple del nodo ---
NODE_IDS: List[str] = ["n1", "n2", "n3"]
NODE_ID: str = os.getenv("NODE_ID", "n1")  # definimos el id por variable de entorno

# --- Peers del sistema (los otros nodos) ---
PEERS: Dict[str, str] = {
    "n1": "http://localhost:8001",
    "n2": "http://localhost:8002",
    "n3": "http://localhost:8003"
}

def make_initial_vc(node_ids: List[str]) -> Dict[str, int]:
    return {nid: 0 for nid in node_ids}

# --- Estado local mínimo (aún sin alumnos) ---
vector_clock: Dict[str, int] = make_initial_vc(NODE_IDS)
store: Dict[str, dict] = {}  
log: List[dict] = []      
hold_back_queue: List[dict] = []

app = FastAPI(title=f"Nodo {NODE_ID}")

# Modelado de clasessss, todas heredan de BaseModel

class Health(BaseModel): # para el /health
    node_id: str
    vector_clock: Dict[str, int]
    store_size: int
    log_size: int

class Alumno(BaseModel): # valida tipo de datos de usuario
    dni: str
    nombre: str
    carrera: str
    anio: int
    nota_promedio: float

# Funciones auxiliares

def replicar_a_peers(dni: str, alumno_data: dict):
    """
    Envía el alumno creado a los demás nodos (excepto a sí mismo).
    """
    for peer_id, peer_url in PEERS.items():
        if peer_id == NODE_ID:
            continue  # no me mando a mí mismo
        try:
            r = requests.post(f"{peer_url}/replicate", json=alumno_data, timeout=3)
            if r.status_code == 200:
                print(f"[{NODE_ID}] Replicado alumno {dni} a {peer_id}")
            else:
                print(f"[{NODE_ID}] Error replicando a {peer_id}: {r.status_code}")
        except Exception as e:
            print(f"[{NODE_ID}] No se pudo conectar con {peer_id}: {e}")

def es_entregable(vc_recibido: Dict[str, int], origen: str) -> bool:
    """
    Determina si una operación es causalmente entregable.
    """
    # 1. Debe ser el siguiente evento del origen
    if vc_recibido[origen] != vector_clock[origen] + 1: # Emisor en la pos de la accion tiene que tener +1 que el propio
        return False

    # 2. Debe conocer todos los eventos previos de los demás
    for nodo, valor in vc_recibido.items():
        if nodo != origen and valor > vector_clock[nodo]: # el nodo que me llega no tiene que saber mas de lo que yo se (sin contar lo mio)
            return False

    return True

def aplicar_operacion(alumno_data: dict):
    """
    Aplica una operación en el nodo local (guardar alumno y actualizar VC).
    """
    dni = alumno_data["dni"]
    store[dni] = alumno_data
    origen = alumno_data["origin"]
    vc_recibido = alumno_data["vc"]

    # Actualiza el VC local: para cada nodo, tomar el máximo
    for nodo in vector_clock.keys():
        vector_clock[nodo] = max(vector_clock[nodo], vc_recibido[nodo])

    log.append({
        "action": "delivered",
        "dni": dni,
        "from": origen,
        "vector_clock": vector_clock.copy(),
        "received_by": NODE_ID
    })

    print(f"[{NODE_ID}] Aplicada operación de {origen} con VC {vc_recibido}")

def procesar_hold_back_queue():
    """
    Revisa las operaciones en espera y aplica las que ya sean entregables.
    """
    pendientes = hold_back_queue.copy()
    for op in pendientes:
        origen = op["origin"]
        if es_entregable(op["vc"], origen):
            aplicar_operacion(op)
            hold_back_queue.remove(op)
            print(f"[{NODE_ID}] Entregada operación en cola de {origen} VC {op['vc']}")

# Endpoints

@app.get("/health", response_model=Health)
def health():
    """
    Endpoint de chequeo: nos muestra el id del nodo y el VC.
    Sirve para validar que cada proceso es "un nodo distinto".
    """
    return Health(
        node_id=NODE_ID,
        vector_clock=vector_clock,
        store_size=len(store),
        log_size=len(log),
    )

@app.post("/alumnos")
def crear_alumno(alumno: Alumno):
    """
    Crea un alumno localmente y actualiza el vector clock del nodo.
    Luego replica la operación a los demás nodos.
    """
    vector_clock[NODE_ID] += 1

    alumno_data = {
        "dni": alumno.dni,
        "nombre": alumno.nombre,
        "carrera": alumno.carrera,
        "anio": alumno.anio,
        "nota_promedio": alumno.nota_promedio,
        "vc": vector_clock.copy(),
        "origin": NODE_ID
    }

    store[alumno.dni] = alumno_data

    log.append({
        "action": "create",
        "dni": alumno.dni,
        "vector_clock": vector_clock.copy(),
        "origin": NODE_ID
    })

    # 🔹 Propagar la operación a los otros nodos
    replicar_a_peers(alumno.dni, alumno_data)

    return {
        "message": f"Alumno {alumno.nombre} creado y replicado desde {NODE_ID}",
        "vector_clock": vector_clock,
        "store_size": len(store)
    }

@app.get("/alumnos")
def listar_alumnos():
    """
    Devuelve todos los alumnos guardados en este nodo.
    """
    return {
        "node_id": NODE_ID,
        "total": len(store),
        "alumnos": store
    }

@app.get("/alumnos/{dni}")
def obtener_alumno(dni: str):
    """
    Devuelve un alumno específico por DNI.
    Si no existe, lanza error 404.
    """
    if dni not in store:
        raise HTTPException(status_code=404, detail=f"Alumno con DNI {dni} no encontrado en {NODE_ID}")

    return {
        "node_id": NODE_ID,
        "alumno": store[dni]
    }

@app.post("/replicate")
def recibir_replicacion(alumno_data: dict):
    """
    Recibe una operación replicada desde otro nodo.
    Verifica si puede aplicarse según el vector clock.
    Si no, la guarda en la hold-back queue.
    """
    dni = alumno_data["dni"]
    origen = alumno_data["origin"]
    vc_recibido = alumno_data["vc"]

    # Si ya lo tengo, lo ignoro (para evitar duplicados)
    if dni in store:
        return {"status": "ignored", "reason": "ya existe"}

    # 1️⃣ Verificamos si la operación es causalmente entregable
    if es_entregable(vc_recibido, origen):
        aplicar_operacion(alumno_data)
        procesar_hold_back_queue()
        return {"status": "delivered", "node": NODE_ID}

    # 2️⃣ Si no es entregable, la guardamos en la cola
    hold_back_queue.append(alumno_data)
    log.append({
        "action": "queued",
        "dni": dni,
        "from": origen,
        "vector_clock": vc_recibido,
        "node": NODE_ID
    })

    print(f"[{NODE_ID}] Operación de {origen} con VC {vc_recibido} no entregable → en cola.")
    return {"status": "queued", "node": NODE_ID}

@app.put("/alumnos/{dni}")
def actualizar_alumno(dni: str, alumno: Alumno):
    """
    Actualiza los datos de un alumno localmente y propaga el cambio.
    Incrementa el vector clock y replica la operación.
    """
    if dni not in store:
        raise HTTPException(status_code=404, detail=f"Alumno {dni} no encontrado en {NODE_ID}")

    # 1️⃣ Incrementar reloj local
    vector_clock[NODE_ID] += 1

    # 2️⃣ Actualizar datos del alumno existente
    alumno_data = {
        "dni": dni,
        "nombre": alumno.nombre,
        "carrera": alumno.carrera,
        "anio": alumno.anio,
        "nota_promedio": alumno.nota_promedio,
        "vc": vector_clock.copy(),
        "origin": NODE_ID
    }
    store[dni] = alumno_data

    # 3️⃣ Registrar en log
    log.append({
        "action": "update",
        "dni": dni,
        "origin": NODE_ID,
        "vector_clock": vector_clock.copy()
    })

    # 4️⃣ Propagar el cambio a los demás nodos
    replicar_a_peers(dni, alumno_data)

    return {
        "message": f"Alumno {dni} actualizado en {NODE_ID}",
        "vector_clock": vector_clock
    }

@app.get("/log")
def ver_log():
    """
    Devuelve el log local completo de este nodo.
    Permite ver las operaciones realizadas o recibidas.
    """
    return {
        "node_id": NODE_ID,
        "log_size": len(log),
        "log": log
    }

@app.get("/queue")
def ver_hold_back_queue():
    """
    Devuelve las operaciones en espera (no entregables aún).
    """
    return {
        "node_id": NODE_ID,
        "queue_size": len(hold_back_queue),
        "hold_back_queue": hold_back_queue
    }
