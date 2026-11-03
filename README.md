# OpenScore Lieder en PDF para YomiScore

Las canciones del [OpenScore Lieder Corpus](https://github.com/OpenScore/Lieder) (comunidad de MuseScore,
licencia **CC0**), convertidas a PDF con MuseScore 3.6.2 para la Biblioteca de YomiScore.

- `scores/<compositor>/<colección>/<canción>/lc<id>.pdf`: un PDF por canción (voz y piano).
- `catalog.tsv`: lo que lee el backend de YomiScore (título, colección, compositor, fechas, letrista, idioma, PDF).
- `state.tsv`: hash de cada fuente convertida, para no repetir trabajo.

El flujo `.github/workflows/render.yml` lo rehace una vez al mes y cuando cambian el flujo o `tools/build.py`;
solo convierte lo nuevo o cambiado.

Créditos: transcripciones de [OpenScore Lieder](https://musescore.com/openscore-lieder-corpus) a partir de
ediciones de dominio público de IMSLP. Esta copia en PDF también se publica con licencia CC0.
