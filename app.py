# python
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, List, Optional
from fastapi import HTTPException
import requests
import os
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from bson.objectid import ObjectId

class DatabaseConnection:
    def __init__(self):
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None

    def connect(self):
        self.client = MongoClient(DBURL)
        self.db = self.client["FIE"]

    def get_collection(self, name: str) -> Collection:
        if self.db is None:
            raise Exception("Database not connected")
        return self.db[name]

    def close(self):
        if self.client:
            self.client.close()

NODE_IDS: List[str] = ["n1", "n2", "n3"]
NODE_ID: str = os.getenv("NODE_ID", "n1")
DBURL: str = os.getenv("DBURL", "mongodb://root:example@localhost:27017")

PEERS: Dict[str, str] = {
    "n1": "http://localhost:8001",
    "n2": "http://localhost:8002",
    "n3": "http://localhost:8003"
}

def make_initial_vc(node_ids: List[str]) -> Dict[str, int]:
    return {nid: 0 for nid in node_ids}

vector_clock: Dict[str, int] = make_initial_vc(NODE_IDS)
log: List[dict] = []
hold_back_queue: List[dict] = []

app = FastAPI(title=f"Nodo {NODE_ID}")
db = DatabaseConnection()
db.connect()
con = db.get_collection("alumnos")

class Health(BaseModel):
    node_id: str
    vector_clock: Dict[str, int]
    db_size: int
    log_size: int

class Alumno(BaseModel):
    dni: str
    nombre: str
    carrera: str
    anio: int
    nota_promedio: float

def serialize_doc(doc: dict) -> dict:
    """
    Convert a MongoDB document to JSON-serializable dict (stringify ObjectId).
    """
    if not doc:
        return doc
    d = doc.copy()
    if "_id" in d and isinstance(d["_id"], ObjectId):
        d["_id"] = str(d["_id"])
    return d

def replicar_a_peers(dni: str, alumno_data: dict):
    """
    Send the created/updated alumno to other peers. Ensure payload is JSON-serializable.
    """
    # make a shallow copy and stringify any ObjectId if present
    payload = {}
    for k, v in alumno_data.items():
        if isinstance(v, ObjectId):
            payload[k] = str(v)
        else:
            payload[k] = v

    for peer_id, peer_url in PEERS.items():
        if peer_id == NODE_ID:
            continue
        try:
            r = requests.post(f"{peer_url}/replicate", json=payload, timeout=3)
            if r.status_code == 200:
                print(f"[{NODE_ID}] Replicado alumno {dni} a {peer_id}")
            else:
                print(f"[{NODE_ID}] Error replicando a {peer_id}: {r.status_code} {r.text}")
        except Exception as e:
            print(f"[{NODE_ID}] No se pudo conectar con {peer_id}: {e}")

def es_entregable(vc_recibido: Dict[str, int], origen: str) -> bool:
    """
    Determine if an operation is causally deliverable.
    Use .get to avoid KeyError when keys are missing.
    """
    # 1. must be the next event from the origin
    if vc_recibido.get(origen, 0) != vector_clock.get(origen, 0) + 1:
        return False

    # 2. must not contain events from others that I don't know
    for nodo, valor in vc_recibido.items():
        if nodo != origen and valor > vector_clock.get(nodo, 0):
            return False

    return True

def aplicar_operacion(alumno_data: dict):
    """
    Apply operation locally: insert alumno and merge vector clocks.
    """
    dni = alumno_data["dni"]
    origen = alumno_data.get("origin")
    vc_recibido = alumno_data.get("vc", {})

    # insert operation (store the incoming payload as-is)
    con.insert_one(alumno_data)

    # merge vector clocks (take max for each node), use .get for safety
    for nodo in vector_clock.keys():
        vector_clock[nodo] = max(vector_clock.get(nodo, 0), vc_recibido.get(nodo, 0))

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
    Check hold-back queue and deliver any now-deliverable operations.
    """
    pendientes = hold_back_queue.copy()
    for op in pendientes:
        origen = op.get("origin")
        if origen is None:
            continue
        if es_entregable(op.get("vc", {}), origen):
            aplicar_operacion(op)
            try:
                hold_back_queue.remove(op)
            except ValueError:
                pass
            print(f"[{NODE_ID}] Entregada operación en cola de {origen} VC {op.get('vc')}")

@app.get("/health", response_model=Health)
def health():
    return Health(
        node_id=NODE_ID,
        vector_clock=vector_clock,
        db_size=con.count_documents({}),
        log_size=len(log),
    )

@app.post("/alumnos")
def crear_alumno(alumno: Alumno):
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

    con.insert_one(alumno_data)

    log.append({
        "action": "create",
        "dni": alumno.dni,
        "vector_clock": vector_clock.copy(),
        "origin": NODE_ID
    })

    replicar_a_peers(alumno.dni, alumno_data)

    return {
        "message": f"Alumno {alumno.nombre} creado y replicado desde {NODE_ID}",
        "vector_clock": vector_clock,
        "db_size": con.count_documents({})
    }

@app.get("/alumnos")
def listar_alumnos():
    """
    Devuelve todos los alumnos como una lista de jsons.
    """
    docs = list(con.find({}))
    alumnos = [serialize_doc(d) for d in docs]
    return {
        "node_id": NODE_ID,
        "total": len(alumnos),
        "alumnos": alumnos
    }

@app.get("/alumnos/{dni}")
def obtener_alumno(dni: str):
    alumno = con.find_one({"dni": dni})
    if alumno is None:
        raise HTTPException(status_code=404, detail=f"Alumno con DNI {dni} no encontrado en {NODE_ID}")
    return {
        "node_id": NODE_ID,
        "alumno": serialize_doc(alumno)
    }

@app.post("/replicate")
def recibir_replicacion(alumno_data: dict):
    dni = alumno_data.get("dni")
    origen = alumno_data.get("origin")
    vc_recibido = alumno_data.get("vc", {})

    if dni is None or origen is None:
        return {"status": "error", "reason": "missing dni/origin"}

    if con.find_one({"dni": dni}) is not None:
        return {"status": "ignored", "reason": "ya existe"}

    if es_entregable(vc_recibido, origen):
        aplicar_operacion(alumno_data)
        procesar_hold_back_queue()
        return {"status": "delivered", "node": NODE_ID}

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
    if con.find_one({"dni": dni}) is None:
        raise HTTPException(status_code=404, detail=f"Alumno {dni} no encontrado en {NODE_ID}")

    vector_clock[NODE_ID] += 1

    alumno_data = {
        "dni": dni,
        "nombre": alumno.nombre,
        "carrera": alumno.carrera,
        "anio": alumno.anio,
        "nota_promedio": alumno.nota_promedio,
        "vc": vector_clock.copy(),
        "origin": NODE_ID
    }
    con.update_one({"dni": dni}, {"$set": alumno_data})

    log.append({
        "action": "update",
        "dni": dni,
        "origin": NODE_ID,
        "vector_clock": vector_clock.copy()
    })

    replicar_a_peers(dni, alumno_data)

    return {
        "message": f"Alumno {dni} actualizado en {NODE_ID}",
        "vector_clock": vector_clock
    }

@app.get("/log")
def ver_log():
    return {
        "node_id": NODE_ID,
        "log_size": len(log),
        "log": log
    }

@app.get("/queue")
def ver_hold_back_queue():
    return {
        "node_id": NODE_ID,
        "queue_size": len(hold_back_queue),
        "hold_back_queue": [serialize_doc(q) if isinstance(q, dict) else q for q in hold_back_queue]
    }
