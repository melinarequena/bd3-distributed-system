# 🧾 Sistema Distribuido con Consistencia Causal
#### Melina Requena
#### Bases de Datos III (BBDD3)
#### Facultad de Ingeniería del Ejército — Ingeniería en Informática


## 📌 Descripción general

Este proyecto implementa un **sistema distribuido simulado** que garantiza **consistencia causal** entre operaciones de lectura y escritura, utilizando **relojes vectoriales (vector clocks)** y **propagación controlada de operaciones** entre nodos.

Cada nodo mantiene su propio estado local, vector de versión, log de operaciones y una cola de espera (hold-back queue) para operaciones que no pueden aplicarse aún por no cumplirse las dependencias causales.

El sistema simula un entorno académico distribuido, donde los nodos gestionan información de **alumnos**, aplicando las propiedades fundamentales de los sistemas distribuidos.

---

## 🏗️ Arquitectura del sistema

### 🔹 Visión general

- **Tres nodos independientes** (N1, N2, N3).  
- Cada nodo:
  - Ejecuta una instancia del servidor **FastAPI**.  
  - Mantiene su propio:
    - `store` → almacenamiento local de alumnos.  
    - `vector_clock` → estado causal del nodo.  
    - `log` → registro local de operaciones.  
    - `hold_back_queue` → cola de operaciones no entregables.

### 🔹 Comunicación entre nodos
- Los nodos se comunican por HTTP.  
- Cuando un nodo realiza una operación local (ej. crear o actualizar un alumno):
  1. Incrementa su propio reloj vectorial.  
  2. Guarda el cambio localmente.  
  3. Propaga la operación a los demás nodos mediante un `POST /replicate`.  
- Cada nodo receptor evalúa si la operación recibida es **causalmente entregable**:
  - ✅ Si lo es, la aplica inmediatamente y actualiza su vector clock.  
  - ⏳ Si no lo es, la guarda en la `hold_back_queue` hasta que lleguen las operaciones previas necesarias.

---

## ⚙️ Tecnologías y Stack

| Componente | Descripción |
|-------------|-------------|
| **Lenguaje** | Python 3.11.9 |
| **Framework Web** | FastAPI |
| **Servidor ASGI** | Uvicorn |
| **Cliente HTTP interno** | `requests` |
| **Modelado de datos** | Pydantic |
| **Entorno** | Windows / Linux / macOS (local o VM) |

### 📦 Dependencias principales
```bash
pip install fastapi uvicorn pydantic requests
```

---

## 🚀 Ejecucion
### 1️⃣ Levantar los tres nodos

---

### Nodo 1
```bash
$env:NODE_ID="n1"
uvicorn app:app --port 8001 --reload
```


### Nodo 2
```bash
$env:NODE_ID="n2"
uvicorn app:app --port 8002 --reload
```

### Nodo 3
```bash
$env:NODE_ID="n3"
uvicorn app:app --port 8003 --reload
```


### 2️⃣ Interfaz de prueba (Swagger)

- Cada nodo expone una documentación interactiva en:

http://localhost:8001/docs
http://localhost:8002/docs
http://localhost:8003/docs


### 🌐 Endpoints principales

| Método | Ruta             | Descripción                                                |
| :----- | :--------------- | :--------------------------------------------------------- |
| `GET`  | `/health`        | Estado del nodo (vector clock, tamaño del store, etc.)     |
| `POST` | `/alumnos`       | Crear un alumno local y propagarlo a los demás nodos       |
| `PUT`  | `/alumnos/{dni}` | Actualizar un alumno y propagar la operación               |
| `GET`  | `/alumnos`       | Listar todos los alumnos del nodo                          |
| `GET`  | `/alumnos/{dni}` | Consultar un alumno específico                             |
| `POST` | `/replicate`     | Recibir una operación desde otro nodo                      |
| `GET`  | `/log`           | Ver el historial completo de operaciones del nodo          |
| `GET`  | `/queue`         | Ver operaciones pendientes en la cola (no entregables aún) |


### 🧪 Casos de prueba demostrativos

#### ✅ Prueba 1: Replicación básica

Crear un alumno en N1 `(POST /alumnos)`.

Verificar que aparece automáticamente en N2 y N3.

Todos los nodos muestran el mismo `vector_clock` actualizado.

Resultado esperado: replicación exitosa entre los tres nodos.

#### ✅ Prueba 2: Causalidad — Operación fuera de orden

Apagar temporalmente N3.

Crear alumno desde `N1 → VC [1,0,0]`.

Actualizar alumno desde `N2 → VC [1,1,0]`.

Encender N3 y enviar primero la actualización de N2, luego la creación de N1.

Observar en N3:

La operación de N2 se pone en cola.

Al llegar la creación de N1, se libera la cola y se aplica todo en orden causal.

Resultado esperado:
`GET /queue` muestra la cola antes y después vacía;
`GET /log` evidencia la entrega diferida.

#### ✅ Prueba 3: Concurrencia

N1 y N2 modifican el mismo alumno casi simultáneamente.

Ambos generan VC distintos (por ejemplo [2,0,0] y [1,1,0]).

N3 recibe ambas operaciones sin relación causal → las aplica como concurrentes (según política elegida: merge o “última versión”).

Resultado esperado:
El sistema demuestra la existencia de versiones concurrentes o resolución determinística.