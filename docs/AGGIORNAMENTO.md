# Come si installa una versione nuova di Aurora

Questa procedura porta un'installazione in esercizio dalla versione che ha
adesso a una piu' recente, **senza perdere niente** e con la strada del
ritorno aperta fino alla fine.

Dura **venti minuti** se non ci sono migrazioni del database, **quaranta** se
ce ne sono. Aurora resta ferma per una decina di minuti: va fatto quando
nell'ufficio tecnico non c'e' nessuno, e avvisando prima.

---

## La regola che regge tutto il documento

> **Prima si fa la copia, poi si tocca.**
>
> Non e' una raccomandazione: e' il passo 2 di questa procedura, e senza di lui
> i passi successivi non si eseguono. Un aggiornamento senza copia preventiva
> non e' un aggiornamento rischioso, e' un aggiornamento **senza ritorno**: se
> una migrazione va storta a meta', il database resta in uno stato che non e'
> ne' quello di prima ne' quello di dopo, e non esiste nessun comando che lo
> rimetta com'era.

---

## Prima di cominciare: quattro cose da avere

| | Perche' |
|---|---|
| La versione nuova, gia' scaricata sul server | scaricarla mentre Aurora e' ferma allunga il fermo |
| L'elenco di che cosa cambia | sta in `docs/STATO.md`, in cima |
| L'ambiente di prova acceso | e' li' che si prova, non in produzione |
| Mezz'ora davanti, senza fretta | un aggiornamento interrotto a meta' e' il caso peggiore |

**Se c'e' l'ambiente di prova, l'aggiornamento si prova prima li'.** La
procedura e' identica, si esegue in `C:\AuroraProva` e sul servizio
`AuroraProva`, e risponde alla sola domanda che conta: *le migrazioni passano
sui dati veri di quest'azienda?* Un aggiornamento provato solo sul portatile
di chi lo ha scritto e' un aggiornamento provato su un database che non
somiglia a questo.

---

## 1. Guardare come sta adesso

Aprire `/diagnostica` e leggere. **Se c'e' gia' una riga rossa, si risolve
quella prima**: aggiornare sopra un guasto vuol dire non sapere piu', dopo, se
il guasto e' quello di prima o uno nuovo.

Annotare la versione di adesso — sta in `/salute`, campo `versione` — e i
conteggi della riga «Quanto c'e' dentro Aurora». Servono al passo 8, per dire
che non si e' perso niente.

```powershell
Invoke-RestMethod https://NOMESERVER:8000/salute |
    Select-Object versione, semaforo
```

---

## 2. La copia di sicurezza preventiva

**Questo passo non si salta**, nemmeno quando la copia notturna e' andata bene
stanotte: fra stanotte e adesso qualcuno ha lavorato, e quel lavoro va
conservato.

```powershell
cd C:\Aurora
.\.venv\Scripts\activate
python scripts\backup.py
```

Deve finire con `Copia completata`. **Annotare il nome della cartella** che
ha scritto: e' quella a cui si torna al passo 9 se qualcosa va storto.

> **Se la copia fallisce, l'aggiornamento non si fa.** Si risolve prima il
> motivo per cui fallisce. Un aggiornamento fatto senza rete sotto e' un
> aggiornamento che, se va male, si porta via i dati dell'azienda.

---

## 3. Fermare Aurora

```powershell
Stop-Service Aurora
Get-Service Aurora
```

Deve rispondere `Stopped`.

**Da questo momento nessuno puo' usare Aurora.** Chi ha una pagina aperta la
vedra' smettere di rispondere: e' il motivo per cui questa procedura si fa
fuori orario.

---

## 4. Mettere da parte la versione di adesso

```powershell
$oggi = Get-Date -Format "yyyy-MM-dd"
Copy-Item -Recurse C:\Aurora "C:\Aurora-prima-del-$oggi" -Exclude .venv,storage,logs,backup
```

E' la strada del ritorno per il **programma**: la copia del passo 2 lo e' per
i **dati**. Sono due cose diverse e servono tutte e due, perche' un ritorno
completo vuol dire rimettere il programma di prima **e** il database di prima.

`storage` non si copia ed e' voluto: e' l'archivio dei documenti, pesa
decine di gigabyte, e non lo tocca nessuna versione di Aurora. I file hanno
per nome l'impronta del proprio contenuto: non cambiano mai e non si
cancellano.

**Le cartelle `C:\Aurora-prima-del-*` si tengono per un mese e poi si
tolgono.** Un anno di aggiornamenti lascia dodici copie del programma sul
disco di sistema.

---

## 5. Portare i file nuovi

Dal repository:

```powershell
cd C:\Aurora
git pull
```

Da una chiavetta: si sovrascrivono le cartelle `app`, `alembic`, `config`,
`docs`, `scripts`, `tests` e i file `requirements.txt`, `alembic.ini`,
`pytest.ini`, `CLAUDE.md`, `README.md`.

> **Il file `.env` non si tocca mai.** Contiene la configurazione di **questa**
> macchina: password, percorsi, certificato. Sovrascriverlo con quello della
> macchina di sviluppo e' il modo piu' rapido di far puntare la produzione al
> database sbagliato. Non e' in git proprio per questo.
>
> Se la versione nuova ha **parametri in piu'**, si aggiungono a mano al `.env`
> esistente: quali siano sta scritto in `docs/STATO.md`, e il commento che
> spiega a che cosa servono sta in `.env.example`. Il passo 6 lo verifica.

Anche le cartelle `storage`, `logs` e `backup` non si toccano.

---

## 6. Le librerie

```powershell
cd C:\Aurora
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
```

Se non e' cambiato niente stampa `Requirement already satisfied` per ogni
riga, e va bene cosi'.

Verifica che la configurazione sia completa:

```powershell
python -c "from app.config import settings; print('configurazione letta')"
```

Se manca un parametro obbligatorio, questo comando si ferma dicendo **quale**:
si aggiunge al `.env` e si riprova. E' il controllo che intercetta il caso del
passo 5.

---

## 7. Le migrazioni del database

**Guardare prima se ce ne sono:**

```powershell
alembic current
alembic heads
```

Se rispondono lo stesso identificativo, non c'e' niente da migrare e si salta
al passo 8.

Se sono diversi, si guarda che cosa verra' eseguito:

```powershell
alembic history --verbose -r current:heads
```

E poi si applica:

```powershell
alembic upgrade head
```

### Le migrazioni che toccano `audit_logs` vanno eseguite come `postgres`

Su questo database `audit_logs` non appartiene piu' ad `aurora_app` e non
accetta `UPDATE` da lui: e' l'irrobustimento della sezione 10
dell'installazione (D-064). Una migrazione che tocchi quella tabella fallisce
con un errore di permessi.

In quel caso si esegue Alembic con le credenziali di `postgres`, per il solo
tempo della migrazione:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:PASSWORD@localhost:5432/aurora"
alembic upgrade head
Remove-Item Env:\DATABASE_URL
```

**La riga `Remove-Item` non e' facoltativa.** Senza, quella variabile resta
nella sessione di PowerShell e i comandi successivi - compreso un eventuale
`backup.py` - girerebbero come `postgres`.

### Se una migrazione fallisce

Ci si ferma li'. **Non si riprova e non si va avanti**: si va al passo 9, il
ritorno alla versione precedente. Una migrazione fallita a meta' lascia il
database in uno stato che non e' ne' quello di prima ne' quello di dopo, e
l'unico modo di uscirne e' rimettere la copia.

---

## 8. Riaccendere e verificare

```powershell
Start-Service Aurora
Get-Service Aurora
```

Poi, **in quest'ordine**:

| # | Che cosa | Come | Risposta attesa |
|---|---|---|---|
| 1 | Aurora risponde | `/salute` | `stato: ok`, e la **versione nuova** |
| 2 | Niente e' rosso | `/diagnostica` | come prima dell'aggiornamento, o meglio |
| 3 | I dati ci sono tutti | riga «Quanto c'e' dentro Aurora» | i conteggi del passo 1, o piu' |
| 4 | Si entra | dal browser, con un profilo vero | il cruscotto |
| 5 | I documenti si aprono | scaricarne uno vecchio | il file arriva e si apre |
| 6 | L'archivio e' a posto | riga «Integrita' dell'archivio» | verde |
| 7 | Il registro continua | riga «Registro delle operazioni» | l'ultima voce e' di adesso |

**La verifica 5 e' quella che conta.** Le altre dicono che il programma e'
partito; questa dice che **i dati di prima sono ancora raggiungibili**, che e'
la cosa che un aggiornamento puo' rompere davvero.

**La verifica 3 vale un minuto di attenzione.** I conteggi devono essere
uguali o **maggiori** di quelli del passo 1. Se sono minori, qualcosa e'
sparito e si va al passo 9 senza discutere.

### Se l'ufficio tecnico e' gia' al lavoro

Si avvisa che l'aggiornamento e' finito e si chiede a **una** persona di fare
il giro che fa tutti i giorni. Un difetto che si vede solo su una pagina
particolare lo trova chi quella pagina la apre venti volte al giorno, non chi
la sta guardando per la prima volta.

---

## 9. Tornare alla versione precedente

Se una delle verifiche non torna, si torna indietro. **Si torna indietro
sempre**: si indaga poi, con calma, sull'ambiente di prova.

### 9a. Se le migrazioni non erano cambiate

E' il caso facile: basta rimettere il programma.

```powershell
Stop-Service Aurora
Remove-Item -Recurse C:\Aurora\app, C:\Aurora\alembic, C:\Aurora\scripts
Copy-Item -Recurse "C:\Aurora-prima-del-DATA\app" C:\Aurora\
Copy-Item -Recurse "C:\Aurora-prima-del-DATA\alembic" C:\Aurora\
Copy-Item -Recurse "C:\Aurora-prima-del-DATA\scripts" C:\Aurora\
Copy-Item "C:\Aurora-prima-del-DATA\requirements.txt" C:\Aurora\
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
Start-Service Aurora
```

Il database non si tocca: era gia' quello giusto.

### 9b. Se erano state applicate delle migrazioni

Il database ha una forma nuova e il programma vecchio non la sa leggere.
Bisogna rimettere tutti e due.

**Prima si prova la discesa di Alembic**, che e' la strada pulita:

```powershell
Stop-Service Aurora
alembic downgrade <identificativo-di-prima>
```

L'identificativo e' quello annotato al passo 7 con `alembic current`. Se la
discesa riesce, si rimette il programma come in 9a e si e' finito.

**Se la discesa fallisce**, o se la migrazione aveva riscritto dei dati, si
rimette la copia del passo 2:

```powershell
cd C:\Aurora
python scripts\ripristino.py
```

Lo script mostra le copie disponibili, chiede **due conferme** - e la prima
non e' «si», e' scrivere per esteso il nome del database che si sta per
sovrascrivere - poi rimette il database, rimette i file mancanti e verifica
che ogni impronta nominata dal database esista davvero sul disco. La procedura
per esteso e' in `docs/BACKUP_E_RIPRISTINO.md`, sezione 6.

Poi si rimette il programma come in 9a.

> **Quello che si perde tornando indietro** e' il lavoro fatto **fra la copia
> del passo 2 e adesso**, cioe' fra mezz'ora fa e adesso. E' la ragione per
> cui questa procedura si fa fuori orario: fuori orario quel lavoro non c'e'.

### 9c. Dirlo

Un ritorno alla versione precedente **va scritto**: che cosa e' successo,
quale verifica non tornava, quale versione e' tornata in servizio. Va in
`docs/STATO.md` e va detto a chi ha scritto la versione nuova, altrimenti
quella versione verra' riproposta identica fra un mese.

---

## 10. Chiudere

- annotare in `docs/STATO.md` la data dell'aggiornamento e la versione
  installata;
- controllare che la **copia notturna** giri ancora: se il percorso di Aurora
  e' cambiato, `scripts\copia_notturna.cmd` va corretto;
- togliere le cartelle `C:\Aurora-prima-del-*` piu' vecchie di un mese;
- se erano cambiati dei parametri di configurazione, riguardare
  `/diagnostica` una seconda volta il giorno dopo: alcune righe (la posta, la
  copia) dicono qualcosa solo dopo che il lavoro pianificato e' girato una
  volta.

---

## Appendice — Riassunto, per chi lo ha gia' fatto altre volte

```powershell
# 1. guardare /diagnostica: se c'e' rosso, risolvere prima

cd C:\Aurora
.\.venv\Scripts\activate

# 2. copia preventiva - NON SI SALTA
python scripts\backup.py

# 3-4. fermare e mettere da parte
Stop-Service Aurora
$oggi = Get-Date -Format "yyyy-MM-dd"
Copy-Item -Recurse C:\Aurora "C:\Aurora-prima-del-$oggi" -Exclude .venv,storage,logs,backup

# 5-6. file nuovi e librerie (il .env non si tocca)
git pull
python -m pip install -r requirements.txt
python -c "from app.config import settings; print('configurazione letta')"

# 7. migrazioni
alembic current; alembic heads
alembic upgrade head

# 8. riaccendere e verificare
Start-Service Aurora
Invoke-RestMethod https://NOMESERVER:8000/salute | Select-Object versione, semaforo
# poi: entrare, aprire /diagnostica, scaricare un documento vecchio
```
