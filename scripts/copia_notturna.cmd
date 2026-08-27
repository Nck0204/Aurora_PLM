@echo off
REM ===========================================================================
REM  Aurora - copia di sicurezza notturna
REM  --------------------------------------------------------------------
REM  Lo esegue l'Utilita' di pianificazione di Windows. La procedura per
REM  programmarlo, con tutte le schede da compilare, e' in
REM  docs\BACKUP_E_RIPRISTINO.md, sezione 5.
REM
REM  DUE COSE DA SAPERE PRIMA DI MODIFICARLO.
REM
REM  1. Il percorso qui sotto va corretto se Aurora non sta in C:\Aurora.
REM     E' l'unica riga da cambiare.
REM
REM  2. L'ultima riga restituisce all'Utilita' di pianificazione il codice di
REM     uscita dello script. Senza, ogni notte risulterebbe riuscita anche
REM     quando la copia fallisce, ed e' esattamente il modo in cui ci si
REM     accorge di non avere copie il giorno in cui servono.
REM
REM  "--silenzioso" stampa solo in caso di guasto: un'operazione che scrive
REM  mezza pagina ogni notte e' un'operazione che dopo un mese nessuno legge
REM  piu'. I guasti vanno comunque sull'uscita degli errori e si vedono.
REM ===========================================================================

cd /d C:\Aurora
if errorlevel 1 (
    echo Non si trova la cartella di Aurora. Correggere il percorso in questo file.
    exit /b 2
)

call .venv\Scripts\activate.bat

python scripts\backup.py --silenzioso

exit /b %ERRORLEVEL%
