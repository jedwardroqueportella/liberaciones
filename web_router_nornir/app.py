from flask import Flask, render_template, request, jsonify, session
from nornir import InitNornir
from nornir.core.task import Result, Task
import paramiko
import socket
import time
import logging
import os
import json
import re
from typing import List, Dict
from datetime import datetime


# ============================================
# CONFIGURACIÓN DE LOGGING MEJORADA
# ============================================
class ColoredFormatter(logging.Formatter):
    """Formatter que agrega colores a los logs"""
    COLORS = {
        'DEBUG': '\033[36m',      # Cian
        'INFO': '\033[32m',       # Verde
        'WARNING': '\033[33m',    # Amarillo
        'ERROR': '\033[31m',      # Rojo
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    def format(self, record):
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}[{record.levelname}]{self.COLORS['RESET']}"
        return super().format(record)

# Configurar logging con mejor formato
log_formatter = ColoredFormatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Handler para consola
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(console_handler)

# Handler para archivo de log
log_file_handler = logging.FileHandler('logs/app_debug.log', encoding='utf-8')
log_file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(log_file_handler)

logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("nornir").setLevel(logging.WARNING)


app = Flask(__name__)
app.secret_key = 'zte_claro_secret_key_2025'


INVENTORY_FILE = "inventory/saved_routers.json"
COMMAND_HISTORY_FILE = "logs/command_history.json"
nr_instance = None


# ============================================
# FUNCIONES MEJORADAS
# ============================================
def load_saved_routers():
    if os.path.exists(INVENTORY_FILE):
        try:
            with open(INVENTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []


def save_routers(routers):
    os.makedirs("inventory", exist_ok=True)
    with open(INVENTORY_FILE, 'w') as f:
        json.dump(routers, f, indent=2)


def load_command_history():
    if os.path.exists(COMMAND_HISTORY_FILE):
        try:
            with open(COMMAND_HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []


def save_command_history(history):
    os.makedirs("logs", exist_ok=True)
    with open(COMMAND_HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)


def create_hosts_yaml(routers, username=None, password=None):
    yaml_content = ""
    for router in routers:
        hostname_in_nornir = router['alias'].replace(' ', '_').replace('-', '_')
        
        # Usar credenciales dinámicas si se proporcionan, sino las guardadas
        final_username = username if username is not None else router.get('username', 'C27747')
        final_password = password if password is not None else router.get('password', 'IzanagI11.')
        
        yaml_content += f"""{hostname_in_nornir}:
  hostname: "{router['ip']}"
  username: "{final_username}"
  password: "{final_password}"
  port: {router.get('port', 22)}
  platform: "zte"
  data:
    real_alias: "{router['alias']}"
    original_ip: "{router['ip']}"
  groups:
    - zte_routers


"""
    
    with open("inventory/hosts.yml", "w") as f:
        f.write(yaml_content)
    
    logger.info(f"Inventario actualizado: {len(routers)} routers con usuario {username}")


# ============================================
# TAREA SSH MEJORADA Y CON MEJOR MANEJO DE ERRORES
# ============================================
def tarea_enviar_comando(task: Task, comando: str) -> Result:
    host = task.host
    output = ""
    real_hostname = ""
    ssh = None
    
    try:
        logger.debug(f"Conectando a {host.name} ({host.hostname})")
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Conexión con timeouts mejorados
        try:
            ssh.connect(
                hostname=str(host.hostname),
                username=str(host.username),
                password=str(host.password),
                port=host.port or 22,
                timeout=20,
                look_for_keys=False,
                allow_agent=False,
                banner_timeout=25,
                auth_timeout=20
            )
            logger.debug(f"✅ Conexión SSH exitosa a {host.name}")
        except paramiko.AuthenticationException as ae:
            logger.error(f"🔐 Error de autenticación en {host.name}: {ae}")
            output = f"🔐 Error de autenticación: Usuario/Contraseña incorrectos"
            return Result(host=task.host, result={
                'output': output,
                'real_hostname': host.data.get('real_alias', host.name),
                'ip': str(host.hostname),
                'alias': host.data.get('real_alias', host.name)
            })
        except socket.timeout:
            logger.error(f"⏱️ Timeout conectando a {host.name}")
            output = f"⏱️ Timeout de conexión (>20s)"
            return Result(host=task.host, result={
                'output': output,
                'real_hostname': host.data.get('real_alias', host.name),
                'ip': str(host.hostname),
                'alias': host.data.get('real_alias', host.name)
            })
        except Exception as ce:
            logger.error(f"❌ Error conectando a {host.name}: {ce}")
            output = f"❌ Error de conexión: {str(ce)}"
            return Result(host=task.host, result={
                'output': output,
                'real_hostname': host.data.get('real_alias', host.name),
                'ip': str(host.hostname),
                'alias': host.data.get('real_alias', host.name)
            })
        
        # Abrir shell interactivo
        channel = ssh.invoke_shell()
        time.sleep(1.5)
        
        # Limpiar buffer inicial
        while channel.recv_ready():
            channel.recv(1024)
        
        # Configurar terminal
        channel.send("terminal length 0\n")
        time.sleep(0.8)
        
        output = ""
        time.sleep(0.5)
        if channel.recv_ready():
            channel.recv(4096)
        
        # Obtener hostname real con mejor manejo de errores
        try:
            channel.send("show running-config | include hostname\n")
            time.sleep(1.5)
            
            if channel.recv_ready():
                hostname_output = channel.recv(4096).decode('utf-8', errors='ignore')
                hostname_match = re.search(r'hostname\s+(\S+)', hostname_output)
                if hostname_match:
                    real_hostname = hostname_match.group(1)
                    host.data['real_hostname'] = real_hostname
                    logger.debug(f"Hostname obtenido: {real_hostname}")
        except Exception as e:
            logger.warning(f"No se pudo obtener hostname real de {host.name}: {e}")
        
        # Limpiar buffer
        time.sleep(0.5)
        while channel.recv_ready():
            channel.recv(1024)
        
        # Ejecutar comando
        logger.info(f"Ejecutando en {real_hostname or host.name}: {comando}")
        channel.send(f"{comando}\n")
        
        max_wait = 10 if 'show run' in comando.lower() else 6
        start_time = time.time()
        last_data_time = start_time
        
        while time.time() - start_time < max_wait:
            time.sleep(0.2)
            
            if channel.recv_ready():
                try:
                    data = channel.recv(4096).decode('utf-8', errors='ignore')
                    if data.strip():
                        output += data
                        last_data_time = time.time()
                except Exception as e:
                    logger.warning(f"Error recibiendo datos de {host.name}: {e}")
                    break
            
            if time.time() - last_data_time > 1.5:
                break
        
        # Limpiar output: remover prompts y líneas no útiles
        try:
            lines = output.split('\n')
            clean_lines = []
            for line in lines:
                line_strip = line.strip()
                # Filtrar líneas no útiles
                if line_strip and not any(prompt in line for prompt in 
                                         ['--More--', 'Press any key', 'Building configuration', 
                                          'terminal length']):
                    clean_lines.append(line)
            
            output = '\n'.join(clean_lines).strip()
            
            if not output:
                output = f"✅ Comando ejecutado sin salida"
                logger.debug(f"Comando sin salida en {host.name}")
        except Exception as e:
            logger.warning(f"Error limpiando output de {host.name}: {e}")
        
        result_data = {
            'output': output,
            'real_hostname': host.data.get('real_alias', host.name),
            'ip': str(host.hostname),
            'alias': host.data.get('real_alias', host.name)
        }
        return Result(host=task.host, result=result_data)
        
    except socket.timeout:
        output = f"⏱️ Timeout de conexión"
        logger.error(f"Timeout en {host.name}")
    except paramiko.AuthenticationException:
        output = f"🔐 Error de autenticación"
        logger.error(f"Error de autenticación en {host.name}")
    except Exception as e:
        output = f"❌ Error: {type(e).__name__}: {str(e)}"
        logger.error(f"Error en {host.name}: {e}")
    finally:
        if ssh:
            try:
                ssh.close()
                logger.debug(f"Conexión cerrada a {host.name}")
            except:
                pass
    
    result_data = {
        'output': output,
        'real_hostname': host.data.get('real_alias', host.name),
        'ip': str(host.hostname),
        'alias': host.data.get('real_alias', host.name)
    }
    return Result(host=task.host, result=result_data)


def tarea_enviar_comandos_batch(task: Task, commands: List[str]) -> Result:
    """Ejecuta una lista de comandos en una sola sesión SSH por host (mantiene la shell abierta)."""
    host = task.host
    output = ""
    real_hostname = ""
    ssh = None

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=str(host.hostname),
            username=str(host.username),
            password=str(host.password),
            port=host.port or 22,
            timeout=20,
            look_for_keys=False,
            allow_agent=False,
            banner_timeout=25,
            auth_timeout=20
        )

        channel = ssh.invoke_shell()
        time.sleep(1.2)
        while channel.recv_ready():
            channel.recv(1024)

        channel.send("terminal length 0\n")
        time.sleep(0.6)

        # intentar obtener hostname
        try:
            channel.send("show running-config | include hostname\n")
            time.sleep(1.2)
            if channel.recv_ready():
                hostname_output = channel.recv(4096).decode('utf-8', errors='ignore')
                m = re.search(r'hostname\s+(\S+)', hostname_output)
                if m:
                    real_hostname = m.group(1)
        except Exception:
            pass

        # Ejecutar todos los comandos en la misma sesión
        for comando in commands:
            channel.send(f"{comando}\n")
            max_wait = 10 if 'show run' in comando.lower() else 6
            start_time = time.time()
            last_data_time = start_time
            cmd_output = ""

            while time.time() - start_time < max_wait:
                time.sleep(0.2)
                if channel.recv_ready():
                    try:
                        data = channel.recv(4096).decode('utf-8', errors='ignore')
                        if data.strip():
                            cmd_output += data
                            last_data_time = time.time()
                    except Exception:
                        break
                if time.time() - last_data_time > 1.5:
                    break

            # limpieza básica
            try:
                lines = cmd_output.split('\n')
                clean_lines = [ln for ln in lines if ln.strip() and not any(x in ln for x in ['--More--','Press any key','Building configuration','terminal length'])]
                cmd_output = '\n'.join(clean_lines).strip()
            except Exception:
                pass

            output += f"\n{'='*60}\nCOMANDO: {comando}\n{'='*60}\n{cmd_output}\n"

        result_data = {
            'output': output.strip() or '✅ Comandos ejecutados sin salida',
            'real_hostname': host.data.get('real_alias', host.name),
            'ip': str(host.hostname),
            'alias': host.data.get('real_alias', host.name)
        }
        return Result(host=task.host, result=result_data)

    except Exception as e:
        output = f"❌ Error: {type(e).__name__}: {str(e)}"
        return Result(host=task.host, result={
            'output': output,
            'real_hostname': host.data.get('real_alias', host.name),
            'ip': str(host.hostname),
            'alias': host.data.get('real_alias', host.name)
        })
    finally:
        if ssh:
            try:
                ssh.close()
            except:
                pass


# ============================================
# RUTAS API - ROUTERS
# ============================================
@app.route('/')
def index():
    routers = load_saved_routers()
    return render_template('index.html', saved_routers=routers)


@app.route('/api/routers', methods=['GET'])
def get_routers():
    routers = load_saved_routers()
    return jsonify({'success': True, 'routers': routers})


@app.route('/api/routers/add', methods=['POST'])
def add_router():
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': '❌ No se recibieron datos'}), 400
        
        ip = data.get('ip', '').strip()
        alias = data.get('alias', '').strip()
        username = data.get('username', 'C27747').strip()
        password = data.get('password', 'IzanagI11.').strip()
        port = int(data.get('port', 22))
        
        # Validar IP
        if not ip:
            logger.warning("Intento de agregar router sin IP")
            return jsonify({'success': False, 'message': '❌ La IP es requerida'}), 400
        
        # Validar formato IP básico
        ip_parts = ip.split('.')
        if len(ip_parts) != 4 or not all(part.isdigit() and 0 <= int(part) <= 255 for part in ip_parts):
            logger.warning(f"Formato IP inválido: {ip}")
            return jsonify({'success': False, 'message': '❌ Formato de IP inválido'}), 400
        
        # Validar puerto
        if port < 1 or port > 65535:
            logger.warning(f"Puerto fuera de rango: {port}")
            return jsonify({'success': False, 'message': '❌ Puerto debe estar entre 1 y 65535'}), 400
        
        routers = load_saved_routers()
        
        # Verificar IP duplicada
        duplicate_action = data.get('duplicate_action', 'reject')
        existing_router = None
        for i, router in enumerate(routers):
            if router['ip'] == ip:
                existing_router = (i, router)
                break
        
        if existing_router:
            if duplicate_action == 'skip':
                logger.info(f"Router {ip} ya existe, saltando")
                return jsonify({'success': True, 'message': '⚠️ Router ya existe, saltado'}), 200
            elif duplicate_action == 'update':
                # Actualizar router existente
                i, router = existing_router
                router.update({
                    'alias': alias or router.get('alias', f"Router_{i+1:03d}"),
                    'username': username,
                    'password': password,
                    'port': port,
                    'updated_date': '2026-01-26 12:00:00'
                })
                save_routers(routers)
                logger.info(f"✅ Router actualizado: {ip} ({router['alias']})")
                return jsonify({
                    'success': True,
                    'message': f'✅ Router actualizado: {ip}',
                    'router': router
                }), 200
            else:
                # Rechazar duplicado (comportamiento original)
                logger.warning(f"Intento de agregar IP duplicada: {ip}")
                return jsonify({'success': False, 'message': '⚠️ Esta IP ya está registrada'}), 400
        
        new_router = {
            'ip': ip,
            'alias': alias or f"Router_{len(routers)+1:03d}",
            'username': username,
            'password': password,
            'port': port,
            'added_date': '2026-01-27 12:00:00',
            'status': 'disconnected',
            'selected': True
        }
        
        routers.append(new_router)
        save_routers(routers)
        
        logger.info(f"✅ Router agregado: {ip} ({new_router['alias']})")
        
        return jsonify({
            'success': True, 
            'message': '✅ Router agregado', 
            'routers': routers
        }), 201
        
    except ValueError as e:
        logger.error(f"Error de validación: {e}")
        return jsonify({'success': False, 'message': f'❌ Datos inválidos: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error en add_router: {e}")
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


@app.route('/api/routers/delete', methods=['POST'])
def delete_router():
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': '❌ No se recibieron datos'}), 400
        
        ip = data.get('ip', '')
        
        if not ip:
            return jsonify({'success': False, 'message': '❌ IP requerida'}), 400
        
        routers = load_saved_routers()
        original_count = len(routers)
        routers = [r for r in routers if r['ip'] != ip]
        
        if len(routers) == original_count:
            logger.warning(f"Intento de eliminar router no encontrado: {ip}")
            return jsonify({'success': False, 'message': '❌ Router no encontrado'}), 404
        
        save_routers(routers)
        logger.info(f"✅ Router eliminado: {ip}")
        
        return jsonify({
            'success': True, 
            'message': '✅ Router eliminado', 
            'routers': routers
        }), 200
        
    except Exception as e:
        logger.error(f"Error en delete_router: {e}")
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


@app.route('/api/routers/select', methods=['POST'])
def select_routers():
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': '❌ No se recibieron datos'}), 400
        
        selected_ips = data.get('selected_ips', [])
        
        routers = load_saved_routers()
        
        for router in routers:
            router['selected'] = router['ip'] in selected_ips
        
        save_routers(routers)
        
        selected_count = sum(1 for r in routers if r['selected'])
        logger.info(f"Routers seleccionados: {selected_count}")
        
        return jsonify({
            'success': True, 
            'message': f'✅ {selected_count} routers seleccionados',
            'routers': routers
        }), 200
        
    except Exception as e:
        logger.error(f"Error en select_routers: {e}")
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


@app.route('/api/routers/test', methods=['POST'])
def test_router():
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': '❌ No se recibieron datos'}), 400
        
        ip = data.get('ip', '')
        username = data.get('username', 'C27747')
        password = data.get('password', 'IzanagI11.')
        port = int(data.get('port', 22))
        
        if not ip:
            return jsonify({'success': False, 'message': '❌ IP requerida'}), 400
        
        logger.info(f"Probando conexión a {ip}:{port}...")
        
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                hostname=ip,
                username=username,
                password=password,
                port=port,
                timeout=10,
                look_for_keys=False,
                allow_agent=False
            )
            
            logger.info(f"✅ Conexión exitosa a {ip}")
            
            # Ejecutar comando de prueba
            stdin, stdout, stderr = ssh.exec_command('show version', timeout=5)
            output = stdout.read().decode('utf-8', errors='ignore')[:200]
            
            ssh.close()
            
            return jsonify({
                'success': True,
                'message': f'✅ Conexión exitosa a {ip}',
                'test_output': output[:100] + '...' if len(output) > 100 else output
            }), 200
            
        except paramiko.AuthenticationException:
            logger.error(f"🔐 Error de autenticación en {ip}")
            return jsonify({
                'success': False,
                'message': f'🔐 Error de autenticación en {ip}: Usuario/Contraseña incorrectos'
            }), 401
        except socket.timeout:
            logger.error(f"⏱️ Timeout conectando a {ip}")
            return jsonify({
                'success': False,
                'message': f'⏱️ Timeout conectando a {ip} (>10s)'
            }), 408
        except Exception as e:
            logger.error(f"❌ Error conectando a {ip}: {e}")
            return jsonify({
                'success': False,
                'message': f'❌ Error conectando a {ip}: {str(e)}'
            }), 500
            
    except ValueError as e:
        logger.error(f"Error de validación: {e}")
        return jsonify({'success': False, 'message': f'❌ Datos inválidos: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error en test_router: {e}")
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


# ============================================
# RUTAS API - CONEXIÓN
# ============================================
@app.route('/api/connect', methods=['POST'])
def connect_routers():
    global nr_instance
    
    try:
        data = request.json
        connect_all = data.get('connect_all', False)
        username = data.get('username', 'C27747')
        password = data.get('password', 'IzanagI11.')
        selected_ips = data.get('selected_ips', None)
        
        logger.info(f"🔗 Intentando conectar - connect_all={connect_all}, usuario={username}")
        
        # Validar que tenemos usuario y contraseña
        if not username or not password:
            logger.error("Usuario o contraseña vacíos")
            return jsonify({
                'success': False,
                'message': '❌ Usuario y contraseña son requeridos'
            }), 400
        
        # Cargar routers
        routers = load_saved_routers()
        logger.info(f"📦 Routers cargados: {len(routers)}")
        
        if not routers:
            logger.warning("No hay routers guardados")
            return jsonify({
                'success': False,
                'message': '❌ No hay routers guardados en el sistema'
            }), 400
        
        # Seleccionar routers
        if connect_all:
            selected_routers = routers
        else:
            if selected_ips:
                selected_routers = [r for r in routers if r['ip'] in selected_ips]
            else:
                selected_routers = [r for r in routers if r.get('selected', True)]
        
        logger.info(f"✓ Routers seleccionados: {len(selected_routers)}")
        
        if not selected_routers:
            logger.warning("No routers seleccionados para conectar")
            return jsonify({
                'success': False,
                'message': '❌ No hay routers seleccionados'
            }), 400
        
        # Crear inventario con credenciales dinámicas
        try:
            create_hosts_yaml(selected_routers, username, password)
            logger.info("📝 Archivo hosts.yml creado correctamente")
        except Exception as yaml_error:
            logger.error(f"❌ Error creando hosts.yml: {yaml_error}", exc_info=True)
            return jsonify({
                'success': False,
                'message': f'❌ Error preparando inventario: {str(yaml_error)}'
            }), 500
        
        # Inicializar Nornir
        try:
            logger.info("⚙️ Inicializando Nornir...")
            nr_instance = InitNornir(config_file="config.yaml")
            logger.info(f"✅ Nornir inicializado con {len(nr_instance.inventory.hosts)} hosts")
        except Exception as nornir_error:
            logger.error(f"❌ Error inicializando Nornir: {nornir_error}", exc_info=True)
            return jsonify({
                'success': False,
                'message': f'❌ Error inicializando sistema: {str(nornir_error)}'
            }), 500
        
        logger.info(f"✅ Conexión exitosa a {len(selected_routers)} routers")
        # Marcar routers seleccionados como conectados y guardar timestamp
        try:
            now_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for r in routers:
                if r in selected_routers:
                    r['status'] = 'connected'
                    r['last_connection'] = now_ts
            save_routers(routers)
        except Exception:
            logger.warning("No se pudo actualizar el estado de routers en inventario")
        
        return jsonify({
            'success': True,
            'message': f'✅ Conectado a {len(selected_routers)} routers',
            'routers': routers,
            'selected_count': len(selected_routers)
        }), 200
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Error en connect_routers: {error_msg}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'❌ Error de conexión: {error_msg}'
        }), 500


# ============================================
# RUTAS API - COMANDOS
# ============================================
@app.route('/api/command', methods=['POST'])
def execute_command():
    global nr_instance
    try:
        data = request.json
        if not data:
            logger.error("No JSON data received in /api/command")
            return jsonify({'success': False, 'output': '❌ Error: No se recibieron datos'}), 400
            
        commands = data.get('commands', [])
        if not commands or not isinstance(commands, list) or len(commands) == 0:
            logger.warning("Empty command received")
            return jsonify({'success': False, 'output': '❌ Comando vacío'}), 400
            
        comando = commands[0].strip()
        save_log = data.get('save_log', True)
        
        if not comando:
            logger.warning("Empty command received")
            return jsonify({'success': False, 'output': '❌ Comando vacío'}), 400
        
        logger.info(f"Comando recibido: {comando}")
        
        # Procesar comando único
        if not nr_instance:
            logger.warning("No Nornir instance connected")
            return jsonify({'success': False, 'output': '⚠️ Primero conecta a los routers'}), 400
        
        logger.info(f"Ejecutando comando en {len(nr_instance.inventory.hosts)} routers")
        
        # Guardar en historial
        history = load_command_history()
        user = data.get('user', 'unknown')
        history.append({
            'command': comando,
            'timestamp': '2026-01-26 12:00:00',  # Timestamp simplificado
            'routers_count': len(nr_instance.inventory.hosts),
            'user': user
        })
        save_command_history(history[-50:])
        
        try:
            logger.info(f"Ejecutando comando: {comando}")
            
            resultados = nr_instance.run(task=tarea_enviar_comando, comando=comando)
            
            salida_final = []
            stats = {'success': 0, 'failed': 0, 'total': len(resultados)}
            
            for nombre_host, resultado_obj in resultados.items():
                try:
                    host = nr_instance.inventory.hosts[nombre_host]
                    
                    if resultado_obj.failed:
                        output_text = f"❌ ERROR: {resultado_obj.exception}"
                        stats['failed'] += 1
                        logger.error(f"Fallo en {nombre_host}: {resultado_obj.exception}")
                        real_hostname = nombre_host
                    else:
                        result_data = resultado_obj.result
                        real_hostname = result_data.get('real_hostname', nombre_host)
                        output_text = result_data.get('output', '')
                        stats['success'] += 1
                        logger.info(f"✅ Éxito en {real_hostname}")
                    
                    salida_final.append(f"\n{'='*70}")
                    salida_final.append(f"🛜 ROUTER: {real_hostname}")
                    salida_final.append(f"📍 IP: {host.hostname}")
                    salida_final.append(f"{'='*70}")
                    salida_final.append(output_text)
                except Exception as e:
                    logger.error(f"Error procesando resultado de {nombre_host}: {e}")
                    salida_final.append(f"\n❌ Error procesando {nombre_host}: {str(e)}")
            
            output_text = '\n'.join(salida_final)
            
            summary = f"\n{'='*70}"
            summary += f"\n📊 COMANDO: {comando}"
            summary += f"\n📈 RESULTADO: {stats['success']}/{stats['total']} routers exitosos"
            if stats['failed'] > 0:
                summary += f" | ❌ Fallos: {stats['failed']}"
            summary += f"\n⏰ Hora: 12:00:00"
            summary += f"\n{'='*70}"
            output_text += summary
            
            if save_log:
                try:
                    timestamp = '20260126_120000'  # Timestamp simplificado
                    if resultados:
                        first_host = list(nr_instance.inventory.hosts.values())[0]
                        hostname_for_file = first_host.data.get('real_alias', 'router').replace(' ', '_')
                    else:
                        hostname_for_file = 'router'
                    
                    log_filename = f"logs/{hostname_for_file}_{timestamp}_cmd.txt"
                    os.makedirs("logs", exist_ok=True)
                    
                    with open(log_filename, 'w', encoding='utf-8') as f:
                        f.write(f"COMANDO EJECUTADO: {comando}\n")
                        f.write(f"FECHA: 2026-01-26 12:00:00\n")
                        f.write(f"TOTAL ROUTERS: {stats['total']}\n")
                        f.write(f"EXITOSOS: {stats['success']}\n")
                        f.write(f"FALLOS: {stats['failed']}\n")
                        f.write(f"\n{'='*80}\n")
                        f.write("RESULTADOS:\n")
                        f.write(f"{output_text}\n")
                    
                    logger.info(f"✅ Log guardado: {log_filename}")
                    
                    return jsonify({
                        'success': True,
                        'output': output_text,
                        'log_file': log_filename,
                        'stats': stats
                    }), 200
                    
                except Exception as e:
                    logger.error(f"Error guardando log: {e}")
                    return jsonify({
                        'success': True,
                        'output': output_text,
                        'stats': stats
                    }), 200
            else:
                return jsonify({
                    'success': True,
                    'output': output_text,
                    'stats': stats
                }), 200
            
        except Exception as e:
            error_msg = f'❌ Error ejecutando comando: {str(e)}'
            logger.error(f"{error_msg}\nError details: {str(e)}")
            return jsonify({'success': False, 'output': error_msg}), 500
        
    except Exception as e:
        error_msg = f'❌ Error procesando comando: {str(e)}'
        logger.error(f"{error_msg}\nError details: {str(e)}")
        return jsonify({'success': False, 'output': error_msg}), 500


@app.route('/api/commands/batch', methods=['POST'])
def execute_commands_batch():
    global nr_instance
    try:
        data = request.json
        if not data:
            logger.error("No JSON data in /api/commands/batch")
            return jsonify({'success': False, 'output': '❌ Error: No se recibieron datos'}), 400
        
        commands = data.get('commands', [])
        save_log = data.get('save_log', True)
        
        if not commands:
            logger.warning("No commands provided")
            return jsonify({'success': False, 'output': '⚠️ No hay comandos para ejecutar'}), 400
        
        if not nr_instance:
            logger.warning("No Nornir instance connected")
            return jsonify({'success': False, 'output': '⚠️ Primero conecta a los routers'}), 400
        
        logger.info(f"Ejecutando {len(commands)} comandos en {len(nr_instance.inventory.hosts)} routers")
        
        all_results = []
        log_files = []
        
        # Guardar en historial
        history = load_command_history()
        user = data.get('user', 'unknown')
        for comando in commands:
            if comando.strip():
                history.append({
                    'command': comando.strip(),
                    'timestamp': '2026-01-26 12:00:00',  # Timestamp simplificado
                    'routers_count': len(nr_instance.inventory.hosts),
                    'user': user
                })
        save_command_history(history[-50:])
        
        try:
            # Ejecutar todos los comandos en una sola sesión por host
            logger.info(f"Ejecutando {len(commands)} comandos en una sola sesión por host")
            resultados = nr_instance.run(task=tarea_enviar_comandos_batch, commands=commands)

            salida_final = []
            stats = {'success': 0, 'failed': 0, 'total': len(resultados)}

            for nombre_host, resultado_obj in resultados.items():
                try:
                    host = nr_instance.inventory.hosts[nombre_host]

                    if resultado_obj.failed:
                        output_text = f"❌ ERROR: {resultado_obj.exception}"
                        stats['failed'] += 1
                        logger.error(f"Fallo en {nombre_host}: {resultado_obj.exception}")
                        real_hostname = nombre_host
                    else:
                        result_data = resultado_obj.result
                        real_hostname = result_data.get('real_hostname', nombre_host)
                        output_text = result_data.get('output', '')
                        stats['success'] += 1
                        logger.info(f"✅ Éxito en {real_hostname}")

                    salida_final.append(f"\n{'='*70}")
                    salida_final.append(f"🛜 ROUTER: {real_hostname}")
                    salida_final.append(f"📍 IP: {host.hostname}")
                    salida_final.append(f"{'='*70}")
                    salida_final.append(output_text)
                except Exception as e:
                    logger.error(f"Error procesando resultado de {nombre_host}: {e}")
                    salida_final.append(f"\n❌ Error procesando {nombre_host}: {str(e)}")

            output_text = '\n'.join(salida_final)

            # Resumen
            summary = f"\n{'='*70}"
            summary += f"\n📊 EJECUCIÓN BATCH: {len(commands)} comandos"
            summary += f"\n📈 RESULTADO: {stats['success']}/{stats['total']} routers exitosos"
            if stats['failed'] > 0:
                summary += f" | ❌ Fallos: {stats['failed']}"
            summary += f"\n⏰ Hora: 12:00:00"
            summary += f"\n{'='*70}"
            output_text += summary

            all_results.append({
                'command': 'batch',
                'output': output_text,
                'stats': stats,
                'index': 1,
                'total_commands': len(commands)
            })

            if save_log:
                try:
                    timestamp = '20260126_120000'  # Timestamp simplificado
                    if resultados:
                        first_host = list(nr_instance.inventory.hosts.values())[0]
                        hostname_for_file = first_host.data.get('real_alias', 'router').replace(' ', '_')
                    else:
                        hostname_for_file = 'router'

                    log_filename = f"logs/{hostname_for_file}_{timestamp}_batch.txt"
                    os.makedirs("logs", exist_ok=True)

                    with open(log_filename, 'w', encoding='utf-8') as f:
                        f.write(f"COMANDOS EJECUTADOS: {len(commands)}\n")
                        f.write(f"FECHA: 2026-01-26 12:00:00\n")
                        f.write(f"TOTAL ROUTERS: {stats['total']}\n")
                        f.write(f"EXITOSOS: {stats['success']} | FALLIDOS: {stats['failed']}\n")
                        f.write("="*70 + "\n")
                        f.write(output_text)

                    log_files.append(log_filename)
                    logger.info(f"✅ Log guardado: {log_filename}")
                except Exception as e:
                    logger.error(f"Error guardando log: {e}")
            
            final_output = "\n\n".join([r['output'] for r in all_results])
            
            total_success = sum(r['stats']['success'] for r in all_results)
            total_failed = sum(r['stats']['failed'] for r in all_results)
            total_routers = all_results[0]['stats']['total'] if all_results else 0
            
            final_output += f"\n\n{'⭐'*35}"
            final_output += f"\n🎯 RESUMEN GENERAL"
            final_output += f"\n{'⭐'*35}"
            final_output += f"\n📋 Total comandos ejecutados: {len(commands)}"
            final_output += f"\n🛜 Routers conectados: {total_routers}"
            final_output += f"\n✅ Comandos exitosos totales: {total_success}"
            final_output += f"\n❌ Fallos totales: {total_failed}"
            final_output += f"\n📁 Logs guardados: {len(log_files)}"
            final_output += f"\n⏰ Finalizado: 2026-01-27 12:00:00"
            final_output += f"\n{'⭐'*35}"
            
            logger.info(f"Ejecución completada: {total_success}/{total_routers} exitosos, {total_failed} fallos")
            
            return jsonify({
                'success': True,
                'output': final_output,
                'all_results': all_results,
                'total_stats': {
                    'commands': len(commands),
                    'routers': total_routers,
                    'success': total_success,
                    'failed': total_failed,
                    'logs': len(log_files)
                },
                'log_files': log_files
            }), 200
            
        except Exception as e:
            error_msg = f'❌ Error ejecutando comandos: {str(e)}'
            logger.error(f"{error_msg}\nError details: {str(e)}")
            return jsonify({'success': False, 'output': error_msg}), 500
    
    except Exception as e:
        error_msg = f'❌ Error crítico en execute_commands_batch: {str(e)}'
        logger.error(f"{error_msg}\nError details: {str(e)}")
        return jsonify({'success': False, 'output': error_msg}), 500


@app.route('/api/commands/history', methods=['GET'])
def get_command_history():
    history = load_command_history()
    return jsonify({'success': True, 'history': history})


# ============================================
# RUTAS API - LOGS
# ============================================
@app.route('/api/logs', methods=['GET'])
def get_logs():
    logs = []
    if os.path.exists("logs"):
        for file in sorted(os.listdir("logs"), reverse=True):
            if file.endswith('.txt'):
                filepath = os.path.join("logs", file)
                stats = os.stat(filepath)
                logs.append({
                    'filename': file,
                    'size_kb': f"{stats.st_size / 1024:.1f}",
                    'date': datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'download_url': f"/api/logs/download/{file}"
                })
    
    return jsonify({'success': True, 'logs': logs[:20]})


@app.route('/api/logs/download/<filename>')
def download_log_file(filename):
    try:
        import base64
        
        # Validar nombre de archivo para evitar path traversal
        if '..' in filename or '/' in filename:
            logger.warning(f"Intento de path traversal: {filename}")
            return jsonify({'success': False, 'message': 'Acceso denegado'}), 403
        
        filepath = os.path.join("logs", filename)
        if os.path.exists(filepath):
            logger.info(f"Descargando log: {filename}")
            with open(filepath, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')
            
            return jsonify({
                'success': True,
                'filename': filename,
                'content': content,
                'size': os.path.getsize(filepath)
            }), 200
        
        logger.warning(f"Archivo no encontrado: {filename}")
        return jsonify({'success': False, 'message': 'Archivo no encontrado'}), 404
        
    except Exception as e:
        logger.error(f"Error descargando log: {e}")
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    try:
        if os.path.exists("logs"):
            files = [f for f in os.listdir("logs") if f.endswith('.txt') or f == 'command_history.json' or f == 'app_debug.log']
            removed_count = 0
            for file in files:
                try:
                    os.remove(os.path.join("logs", file))
                    removed_count += 1
                except Exception as e:
                    logger.warning(f"Error eliminando {file}: {e}")
            
            logger.info(f"✅ Borrados {removed_count} archivos de logs")
            return jsonify({
                'success': True, 
                'message': f'✅ Borrados {removed_count} archivos de logs'
            }), 200
        
        logger.info("No hay carpeta logs")
        return jsonify({'success': True, 'message': '✅ No hay logs para borrar'}), 200
        
    except Exception as e:
        logger.error(f"Error borrando logs: {e}")
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


# ============================================
# RUTAS API - SISTEMA
# ============================================
@app.route('/api/system/status', methods=['GET'])
def system_status():
    routers = load_saved_routers()
    log_count = len([f for f in os.listdir("logs") if f.endswith('.txt')]) if os.path.exists("logs") else 0
    
    return jsonify({
        'success': True,
        'status': {
            'routers_count': len(routers),
            'connected': nr_instance is not None,
            'logs_count': log_count,
            'timestamp': '2026-01-27 12:00:00',
            'hostname': os.uname().nodename if hasattr(os, 'uname') else 'N/A'
        }
    })


@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    global nr_instance
    try:
        if nr_instance:
            try:
                nr_instance.close_connections()
                logger.info("Conexiones cerradas")
            except Exception as e:
                logger.warning(f"Error cerrando conexiones: {e}")
            finally:
                nr_instance = None
        
        routers = load_saved_routers()
        for router in routers:
            router['status'] = 'disconnected'
        save_routers(routers)
        
        logger.info("✅ Desconectado de todos los routers")
        
        return jsonify({'success': True, 'message': '✅ Desconectado de todos los routers'}), 200
        
    except Exception as e:
        logger.error(f"Error en disconnect: {e}")
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


# ============================================
# INICIALIZACIÓN
# ============================================
if __name__ == '__main__':
    os.makedirs("inventory", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    print("="*80)
    print("  🚀 ADMINISTRADOR ZTE CLARO - VERSIÓN COMPLETA")
    print("  ✨ TODAS LAS RUTAS API INCLUIDAS:")
    print("     • /api/routers/* - Gestión de routers")
    print("     • /api/commands/* - Comandos simples y múltiples")
    print("     • /api/logs/* - Logs con hostname real")
    print("     • /api/system/* - Estado del sistema")
    print("")
    print("  🌐 Acceso: http://0.0.0.0:5000")
    print("  📁 Logs con nombre real: logs/rCSRSaulCantoral_*.txt")
    print("="*80)
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False, threaded=True)


