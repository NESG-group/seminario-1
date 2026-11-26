# Seminario 1: Demo del asistente VIGILANT para tareas de análisis de tráfico de red

En esta sesión se presenta el estado actual de **VIGILANT**, como un asistente
conversacional diseñado para apoyar tareas de análisis de tráfico de red. Durante la demo,
los participantes utilizarán el agente y su interfaz web para responder a una serie de
preguntas concretas sobre una captura de tráfico correspondiente a un **escenario de
ransomware** en el que se ha ejecutado el binario **CryLock** (variante de la familia
Cryakl/CryLock).

El reto consiste en formular las preguntas adecuadas al asistente y utilizar únicamente la
información que este devuelva en el chat para responder el cuestionario. No se permite el
uso de herramientas externas de análisis de PCAP ni consultar otras fuentes: el asistente es
la única fuente de información válida para la demo.

## Acceso a las herramientas

Los participantes utilizarán dos plataformas durante la demo. Ambas usan un certificado
interno: si el navegador muestra un aviso de seguridad, aceptadlo para continuar.

### Chat con el asistente VIGILANT

- **URL de acceso:** <https://172.25.203.122>
- **Autenticación:** con el usuario asignado a cada participante.
- **Identificación de la traza:** para preguntar sobre la captura, indicad al asistente el
  siguiente ID de traza: `12d3d2ca-8bf4-43ce-afb8-7d54dca7beab`
- **Uso:** escribid vuestras preguntas en lenguaje natural. El asistente analizará la traza
  referenciada y responderá en base al contenido del PCAP y de los logs asociados.
  Toda respuesta que se utilice en el formulario debe provenir del chat.

### Formulario de respuestas

- **URL de acceso:** <https://172.25.203.122:9443/>
- **Autenticación:** con el mismo usuario asignado.
- **Envío:** cada participante rellena sus respuestas directamente en el formulario. El
  sistema valida los intentos y calcula la puntuación automáticamente.

## Reglas del reto

- **Fuente única de información:** solo se consideran válidas las respuestas obtenidas
  del asistente VIGILANT en el chat. Queda prohibido el uso de analizadores de PCAP
  externos, buscadores u otras fuentes.
- **Formular las preguntas:** el formulario indica qué hay que averiguar en cada pregunta,
  pero no cómo preguntarlo: cada participante redacta su propia pregunta al asistente.
- **Pistas:** si os atascáis, cada pregunta ofrece una pista con la pregunta exacta para
  copiar y pegar en el chat. Usarla **resta 50 puntos** a esa pregunta (antes de aplicar
  el bonus por rapidez y nunca por debajo del mínimo de 25).
- **Intentos por pregunta:** cada pregunta tiene un **límite de 3 intentos**.
- **Penalización:** cada pregunta vale 100 puntos y cada respuesta incorrecta **resta 25**
  (mínimo 25 si se acaba acertando).
- **Bonus por rapidez:** en cada pregunta, quien acierta antes que el resto multiplica sus
  puntos: la **1ª persona ×2**, la 2ª ×1,75, la 3ª ×1,5, la 4ª ×1,25 y el resto ×1. El
  formulario muestra cuántas personas han resuelto ya cada pregunta y qué multiplicador queda.
- **Puntuación final:** se calcula de forma automática en función de los aciertos, los
  intentos consumidos, las pistas usadas y la rapidez. Gana quien más puntos tenga; en caso de empate, quien
  terminó antes.
- **Ranking:** se puede consultar en directo el **ranking de usuarios** y los últimos
  aciertos desde el propio formulario, para comparar resultados con el resto de participantes.
- **Uso individual:** cada participante trabaja con su propio usuario; no se permite
  compartir cuentas ni respuestas entre participantes.
