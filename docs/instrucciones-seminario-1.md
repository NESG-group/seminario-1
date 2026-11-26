# Seminario 1: Demo del asistente VIGILANT para tareas de análisis de tráfico de red

En esta sesión se presenta el estado actual de **VIGILANT**, como un asistente
conversacional diseñado para apoyar tareas de análisis de tráfico de red. Durante la demo,
los participantes utilizarán el agente y su interfaz web para responder a una serie de
preguntas concretas sobre una captura de tráfico correspondiente a un **escenario de
ransomware** en el que se ha ejecutado el binario **CryLock** (variante de la familia
Cryakl/CryLock).

La captura utilizada es un extracto obtenido del
[dataset público de la Universidad Pública de Navarra](http://dataset.tlm.unavarra.es/ransomware/php/moreInfo.php?sample=CryLock_24012021).

El reto consiste en formular las preguntas adecuadas al asistente y utilizar únicamente la
información que este devuelva en el chat para responder el cuestionario. No se permite el
uso de herramientas externas de análisis de PCAP ni consultar otras fuentes: el asistente es
la única fuente de información válida para la demo.

## Acceso a las herramientas

Los participantes utilizarán dos plataformas durante la demo. Ambas usan un certificado
interno: si el navegador muestra un aviso de seguridad, aceptadlo para continuar.

### Chat con el asistente VIGILANT

- **URL de acceso:** `https://<DEMO_HOST>`
- **Autenticación:** con el usuario asignado a cada participante.
- **Captura:** descargad la captura desde el formulario de respuestas (enlace
  *descarga la captura*) y adjuntadla en el chat al empezar la conversación. Haced
  todas las preguntas en esa misma conversación.
- **Uso:** escribid vuestras preguntas en lenguaje natural. El asistente analizará la traza
  adjunta y responderá en base al contenido del PCAP y de los logs asociados.
  Toda respuesta que se utilice en el formulario debe provenir del chat.

### Formulario de respuestas

- **URL de acceso:** `https://<DEMO_HOST>:9443`
- **Autenticación:** con el mismo usuario asignado.
- **Envío:** cada participante rellena sus respuestas directamente en el formulario. El
  sistema valida los intentos y calcula la puntuación automáticamente.

## Reglas del reto

- **Fuente única de información:** solo se consideran válidas las respuestas obtenidas
  del asistente VIGILANT en el chat. Queda prohibido el uso de analizadores de PCAP
  externos, buscadores u otras fuentes.
- **Intentos por pregunta:** cada pregunta tiene un **límite de 3 intentos**.
- **Penalización:** cada respuesta incorrecta **resta puntos** sobre la puntuación máxima
  disponible de esa pregunta.
- **Puntuación final:** se calcula de forma automática en función del número de aciertos
  y de los intentos consumidos.
- **Ranking:** se puede consultar el **ranking de usuarios** desde el propio formulario,
  para comparar resultados con el resto de participantes.
- **Uso individual:** cada participante trabaja con su propio usuario; no se permite
  compartir cuentas ni respuestas entre participantes.
