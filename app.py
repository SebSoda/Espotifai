from flask import Flask, render_template, request, redirect, session, flash, get_flashed_messages
from cassandra.cluster import Cluster

app = Flask(__name__)
app.secret_key = 'secreto123'  # Necesario para sesiones

# Conexión a Cassandra
cluster = Cluster(['127.0.0.1'])
session_cassandra = cluster.connect('musica_recomendacion')


@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    usuario_id = int(request.form['usuario_id'])

    fila = session_cassandra.execute("SELECT * FROM usuarios WHERE usuario_id=%s", (usuario_id,)).one()
    if fila:
        session['usuario_id'] = usuario_id
        session['nombre'] = fila.nombre
        return redirect('/reproductor')
    else:
        return "Usuario no encontrado", 404


@app.route('/registrar', methods=['POST'])
def registrar():
    usuario_id = int(request.form['usuario_id'])
    nombre = request.form['nombre']
    ciudad = request.form['ciudad']

    fila = session_cassandra.execute("SELECT * FROM usuarios WHERE usuario_id=%s", (usuario_id,)).one()
    if fila:
        return "Usuario ya existe", 400

    session_cassandra.execute("""
        INSERT INTO usuarios (usuario_id, nombre, ciudad)
        VALUES (%s, %s, %s)
    """, (usuario_id, nombre, ciudad))

    return redirect('/')

@app.route('/reproducir', methods=['POST'])
def reproducir():
    if 'usuario_id' not in session:
        return redirect('/')

    usuario_id = session['usuario_id']
    cancion_id = int(request.form['cancion_id'])
    fecha = datetime.now()

    # Registrar escucha en Cassandra
    session_cassandra.execute("""
        INSERT INTO escuchas_por_usuario (usuario_id, fecha_escucha, cancion_id)
        VALUES (%s, %s, %s)
    """, (usuario_id, fecha, cancion_id))

    genero = session_cassandra.execute("SELECT genero FROM canciones WHERE cancion_id=%s", (cancion_id,)).one().genero
    anio = fecha.year
    mes = fecha.month

    # Actualizar tabla OLAP
    session_cassandra.execute("""
        UPDATE escuchas_por_genero_y_mes SET total_escuchas = total_escuchas + 1
        WHERE genero=%s AND anio=%s AND mes=%s
    """, (genero, anio, mes))

    session_cassandra.execute("""
        UPDATE escuchas_totales_por_genero SET total_escuchas = total_escuchas + 1
        WHERE genero=%s
    """, (genero,))

    # Obtener título para mostrar mensaje
    fila = session_cassandra.execute("SELECT titulo FROM canciones WHERE cancion_id=%s", (cancion_id,)).one()
    titulo = fila.titulo if fila else "una canción"

    flash(f'Estás reproduciendo "{titulo}" 🎶')
    return redirect('/reproductor')


@app.route('/reproductor')
def reproductor():
    usuario_id = session.get('usuario_id')
    if not usuario_id:
        return redirect('/')

    ciudad = session_cassandra.execute("SELECT ciudad FROM usuarios WHERE usuario_id=%s", (usuario_id,)).one().ciudad
    usuarios = session_cassandra.execute("SELECT usuario_id FROM usuarios WHERE ciudad=%s ALLOW FILTERING", (ciudad,))
    usuarios_ids = [u.usuario_id for u in usuarios]

    conteo = {}
    for uid in usuarios_ids:
        escuchas = session_cassandra.execute("SELECT cancion_id FROM escuchas_por_usuario WHERE usuario_id=%s", (uid,))
        for fila in escuchas:
            conteo[fila.cancion_id] = conteo.get(fila.cancion_id, 0) + 1

    recomendadas = []
    recomendadas_ids = set()
    for cancion_id, total in sorted(conteo.items(), key=lambda x: -x[1]):
        fila = session_cassandra.execute("SELECT * FROM canciones WHERE cancion_id=%s", (cancion_id,)).one()
        if fila:
            recomendadas.append({
                'cancion_id': cancion_id,
                'titulo': fila.titulo,
                'artista': fila.artista,
                'genero': fila.genero,
                'total_escuchas': total
            })
            recomendadas_ids.add(cancion_id)

    # Otras canciones (no recomendadas)
    todas = session_cassandra.execute("SELECT * FROM canciones")
    otras = []
    for fila in todas:
        if fila.cancion_id not in recomendadas_ids:
            otras.append({
                'cancion_id': fila.cancion_id,
                'titulo': fila.titulo,
                'artista': fila.artista,
                'genero': fila.genero
            })

    return render_template("reproductor.html",
                           nombre=session['nombre'],
                           ciudad=ciudad,
                           canciones=recomendadas,
                           otras_canciones=otras)



@app.route('/usuarios')
def usuarios():
    rows = session.execute("SELECT * FROM usuarios")
    return render_template('usuarios.html', usuarios=rows)

@app.route('/canciones')
def canciones():
    rows = session.execute("SELECT * FROM canciones")
    return render_template('canciones.html', canciones=rows)

@app.route('/escuchas')
def escuchas():
    rows = session.execute("SELECT * FROM escuchas_por_usuario")
    return render_template('escuchas.html', escuchas=rows)
    
    # Paso 1: obtener la ciudad del usuario actual
def obtener_ciudad(usuario_id):
    fila = session.execute("SELECT ciudad FROM usuarios WHERE usuario_id=%s", (usuario_id,)).one()
    return fila.ciudad if fila else None

# Paso 2: obtener canciones más escuchadas en esa ciudad
def canciones_populares_en_ciudad(ciudad):
    usuarios = session.execute("SELECT usuario_id FROM usuarios WHERE ciudad=%s ALLOW FILTERING", (ciudad,))
    usuarios_ids = [fila.usuario_id for fila in usuarios]

    conteo_canciones = {}
    for uid in usuarios_ids:
        escuchas = session.execute("SELECT cancion_id FROM escuchas_por_usuario WHERE usuario_id=%s", (uid,))
        for fila in escuchas:
            conteo_canciones[fila.cancion_id] = conteo_canciones.get(fila.cancion_id, 0) + 1

    canciones = []
    for cancion_id, conteo in sorted(conteo_canciones.items(), key=lambda x: -x[1]):
        titulo = session.execute("SELECT titulo FROM canciones WHERE cancion_id=%s", (cancion_id,)).one().titulo
        canciones.append((titulo, conteo))
    return canciones

from datetime import datetime

def agregar_escucha(usuario_id, cancion_id, fecha):
    session.execute("""
        INSERT INTO escuchas_por_usuario (usuario_id, fecha_escucha, cancion_id)
        VALUES (%s, %s, %s)
    """, (usuario_id, fecha, cancion_id))

    genero = session.execute("SELECT genero FROM canciones WHERE cancion_id=%s", (cancion_id,)).one().genero
    anio = fecha.year
    mes = fecha.month

    # Actualizar cubo OLAP (contador por género y mes)
    session.execute("""
        UPDATE escuchas_por_genero_y_mes SET total_escuchas = total_escuchas + 1
        WHERE genero=%s AND anio=%s AND mes=%s
    """, (genero, anio, mes))

    # También puedes actualizar escuchas_totales_por_genero si quieres
    session.execute("""
        UPDATE escuchas_totales_por_genero SET total_escuchas = total_escuchas + 1 WHERE genero=%s
    """, (genero,))


def total_escuchas_por_genero_y_mes():
    resultados =session_cassandra.execute("SELECT * FROM escuchas_por_genero_y_mes")
    return [
        {'genero': row.genero, 'anio': row.anio, 'mes': row.mes, 'total': row.total_escuchas}
        for row in resultados
    ]


def total_escuchas_por_genero():
    resultados = session_cassandra.execute("SELECT * FROM escuchas_totales_por_genero")
    return [{'genero': row.genero, 'total': row.total_escuchas} for row in resultados]

@app.route("/olap")
def mostrar_olap():
    datos = total_escuchas_por_genero_y_mes()
    return render_template("olap.html", datos=datos)

@app.route("/graficos")
def ver_graficos():
    datos_por_genero_mes = total_escuchas_por_genero_y_mes()
    datos_totales_genero = total_escuchas_por_genero()
    return render_template("graficos.html",
                           datos_mes=datos_por_genero_mes,
                           datos_totales=datos_totales_genero)


if __name__ == '__main__':
    app.run(debug=True)
