"""Frente B: nombre antiguo del analizador de descripciones (era el placeholder que solo buscaba <IMPORTANT>).

Se mantiene para que sigan funcionando los comandos y tests que usan
`frente_b_descripciones.analizador`: ahora corre las heurísticas completas.

Para comparar técnicas, el pipeline registra los dos módulos por separado:
    frente_b_descripciones.heuristicas       heurísticas
    frente_b_descripciones.clasificador_llm  LLM-as-judge
No registrar este alias junto con heuristicas: los hallazgos saldrían repetidos.
"""
from frente_b_descripciones.heuristicas import analizar

__all__ = ["analizar"]
