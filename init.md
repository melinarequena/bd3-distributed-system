# **Iniciar todo**



#### **Nodo 1**



$env:NODE\_ID = "n1"

uvicorn app:app --host 127.0.0.1 --port 8001 --reload



http://127.0.0.1:8001/docs





#### **Nodo 2**



$env:NODE\_ID = "n2"

uvicorn app:app --host 127.0.0.1 --port 8002 --reload

http://127.0.0.1:8002/docs





#### **Nodo 3**



$env:NODE\_ID = "n3"

uvicorn app:app --host 127.0.0.1 --port 8003 --reload

http://127.0.0.1:8003/docs/





