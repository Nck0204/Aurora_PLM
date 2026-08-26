# Aurora

Gestione progetti e documentazione tecnica. Gira in rete locale, senza cloud.

## Avvio in sviluppo

1. Preparare il database seguendo `scripts/setup_postgres.md` (parte B).
2. Copiare `.env.example` in `.env` e adattare `DATABASE_URL`.
3. Creare l'ambiente virtuale: `python -m venv .venv`
4. Attivarlo: `.venv\Scripts\activate`
5. Installare le dipendenze: `pip install -r requirements.txt`
6. Applicare le migrazioni: `alembic upgrade head`
7. Creare i dati iniziali: `python scripts/seed.py`
   Stampa **una volta sola** la password dell'utente `admin`: annotarla.
8. Avviare il server: `uvicorn app.main:app --reload`
9. Controllare che sia vivo: <http://localhost:8000/salute> (attesa: `"stato": "ok"`)
10. Entrare: <http://localhost:8000/entra>, utente `admin` con la password del
    punto 7. Al primo accesso il programma obbliga a cambiarla.
11. Rendere il registro delle operazioni a sola aggiunta, seguendo
    `scripts/hardening_db.md`. **Va fatto dopo il punto 6 e non prima**: la
    migrazione riempie le colonne delle righe gia' scritte, ed e' l'ultimo
    `UPDATE` che verra' mai eseguito su quella tabella.
12. Eseguire i test: `pytest`
13. In caso di problemi, leggere il registro: `Get-Content logs\aurora.log -Tail 50`

## Dove finiscono i file caricati

In `STORAGE_PATH` (di partenza `storage/`), depositati con il nome della loro
impronta SHA-256 e non con il loro:

```
storage/objects/3f/9a/3f9a2c11...   il file
storage/tmp/                        i file a meta' scrittura
storage/posta/                      la cartella della posta (MAIL_LOCAL_PATH)
```

Il nome originale, il tipo e tutti i metadati stanno nel database. Due
caricamenti dello stesso identico file occupano un file solo. La cartella
`tmp/` in condizioni normali e' vuota: quello che ci resta e' un caricamento
interrotto, e non lo riferisce nessuna riga del database.

**`STORAGE_PATH` va nei backup del server**: il database senza quella cartella
e' un elenco di documenti che non si aprono. In produzione conviene un disco
dedicato.

## Chi vede che cosa

Un utente accede a un documento se e' il **creatore**, se e' il **project
manager** del progetto a cui il documento appartiene, oppure se e' **assegnato**
a quel progetto e la matrice dei permessi consente al suo ruolo quell'operazione
su quella classificazione.

La matrice si corregge da <http://localhost:8000/permessi> (serve il ruolo di
creatore): una riga per ruolo di progetto, tre spunte per classificazione. Il
salvataggio passa da una conferma che elenca che cosa cambia, e ogni casella
corretta finisce nel registro delle operazioni con il valore precedente e
quello successivo. **Ha effetto subito**, anche su chi e' collegato in quel
momento: nessuno deve uscire e rientrare.

Per sapere che cosa vede una persona senza entrare con le sue credenziali:
dall'elenco degli utenti, il pulsante **Verifica accessi**.

Nel codice la regola sta in un punto solo, `app/services/permissions.py`, e ci
si arriva sempre con `permissions.puo(db, utente, azione, oggetto)`. Non ci sono
controlli di permesso da nessun'altra parte, nemmeno nei template: c'e' un test
che lo verifica leggendo i sorgenti.

## Il registro delle operazioni

Ogni operazione che cambia qualcosa in Aurora lascia una riga in `audit_logs`:
chi, che cosa, su quale oggetto, quando, da quale indirizzo, con il valore di
prima e quello di dopo e una frase in italiano che si capisce senza conoscere
il programma.

Si consulta da <http://localhost:8000/registro> (serve il ruolo di creatore),
con i filtri per intervallo di date, utente, tipo di azione e tipo di oggetto,
e la ricerca sulla descrizione. Da li' si esporta in CSV quello che si sta
guardando - e l'esportazione stessa finisce nel registro.

La storia di un oggetto singolo si guarda invece dalla sua scheda, linguetta
**Storico**: prodotti, versioni, progetti, documenti, messaggi di posta e
persone ce l'hanno tutti, e la vede chi vede l'oggetto.

**Le righe si aggiungono e non si tolgono.** Non e' una promessa del programma:
l'utente PostgreSQL con cui Aurora si collega ha su quella tabella `SELECT` e
`INSERT` e nient'altro. Si verifica cosi':

```powershell
psql -U aurora_app -h localhost -d aurora -c "UPDATE audit_logs SET description = 'x' WHERE seq = 1;"
```

La risposta attesa e' `permesso negato per la tabella audit_logs`. Se invece
risponde `UPDATE 1`, l'irrobustimento non e' stato applicato: vedi
`scripts/hardening_db.md`.

In piu', ogni voce porta l'impronta della precedente, cosi' una manomissione
fatta scavalcando il programma - da chi amministra il database - resta
comunque visibile:

```powershell
python scripts/verifica_audit.py
```

Le voci **non si cancellano mai**, nemmeno le piu' vecchie. Per consegnarne una
copia a chi verifica, o per tenerne una fuori dal database, c'e'
`python scripts/archivia_audit.py --anni 5`, che scrive un file compresso e non
tocca il database.

## La posta

Aurora archivia i messaggi di posta e li attacca alla **versione di prodotto**
di cui parlano. Il file `.eml` originale si conserva intero nell'archivio, come
ogni altro file, e resta sempre scaricabile.

**Da dove arrivano.** Lo dice `MAIL_PROVIDER` nel file `.env`. Con `locale`,
che e' quello che si usa oggi, Aurora legge i file `.eml` che trova in
`MAIL_LOCAL_PATH` e, dopo averli archiviati, li sposta:

```
storage/posta/               i messaggi ancora da leggere
storage/posta/elaborate/     quelli archiviati e attribuiti
storage/posta/quarantena/    quelli che aspettano una persona
```

Il collegamento alla casella aziendale (Microsoft Graph) arriva con la sessione
11: fino ad allora `MAIL_PROVIDER=graph` si ferma con un messaggio che lo
spiega, invece di far credere che la casella sia vuota.

**Come si prova, senza toccare nessuna casella:**

```powershell
python scripts/genera_email_prova.py
```

Scrive ventiquattro messaggi che esercitano tutti i casi - oggetti corretti,
con `R:` e `Fwd:` davanti, senza codice, risposte in conversazione, allegati
grandi e accentati, un file malformato - usando i codici dei prodotti veri del
database. Poi si apre <http://localhost:8000/posta> e si preme **Elabora la
posta**. Rieseguendo tutto una seconda volta non compare nessun doppione.

**Come Aurora capisce a chi appartiene un messaggio**, nell'ordine:

1. l'oggetto scritto secondo la convenzione `[CODICE][Vn][MOTIVO]`,
   riconosciuto anche dietro a `R:`, `Re:`, `Fwd:`, `I:` accumulati;
2. il codice prodotto scritto in mezzo alla frase, senza parentesi;
3. il filo di conversazione: se un altro messaggio dello stesso scambio e' gia'
   archiviato e attribuito, si eredita la sua attribuzione;
4. la **quarantena**, che non e' un errore ma una domanda a una persona.

Il messaggio viene archiviato **sempre**, anche quando il file e' rovinato o
l'oggetto non dice niente: in quarantena, con scritto perche' e' li'.

**La quarantena** sta in <http://localhost:8000/posta/quarantena> (serve il
ruolo di creatore, perche' un messaggio non attribuito non appartiene a nessun
progetto e non c'e' nessuna matrice da consultare). Assegnando un messaggio,
Aurora propone di assegnare allo stesso prodotto anche gli altri messaggi della
stessa conversazione.

**Le sigle dei motivi** - `SPECS`, `RFQ`, `QUOTE`... - si cambiano da
<http://localhost:8000/posta/motivi>. Non governano lo smistamento: un
messaggio con un motivo fuori elenco viene attribuito lo stesso.

**Chi vede la posta** e' deciso dalla stessa matrice dei documenti: un
messaggio e' trattato come un documento di classificazione **Corrispondenza**
nel progetto della versione a cui e' attaccato.

## Se nessuno riesce piu' a entrare

Le password non si recuperano: nel database c'e' solo l'impronta argon2. Se ne
assegna una nuova dalla riga di comando, sul server:

```powershell
python scripts/reimposta_password.py admin
```

Stampa una password nuova, obbliga a cambiarla al primo accesso e chiude tutte
le sessioni aperte di quell'utente. Funziona con qualunque nome utente, non
solo `admin`, e sa riattivare un utente disattivato.

## Da leggere prima di modificare il codice

- `CLAUDE.md` — convenzioni e regole permanenti del progetto
- `docs/STATO.md` — a che punto e' il lavoro
- `docs/DECISIONI.md` — le decisioni tecniche prese e il perche'
- `docs/GUIDA_STILE.md` — palette e componenti, prima di scrivere una pagina

I componenti dell'interfaccia si vedono tutti insieme, in tutte le varianti,
all'indirizzo <http://localhost:8000/stile> (serve il ruolo di creatore).
