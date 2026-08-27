# Chi vede che cosa

In Aurora nessuno vede tutto, tranne chi amministra il programma. Questa pagina
spiega la regola, che e' una sola e vale dappertutto: sui documenti, sui
progetti, sulla posta.

## La regola in una frase

**Si vede quello che riguarda i progetti a cui si e' assegnati, e dentro quei
progetti si vede quello che il proprio ruolo permette di vedere della
classificazione di quel documento.**

Sono due condizioni e servono tutte e due. Non basta essere nel progetto: se
sei un ingegnere e il documento e' commerciale, non lo vedi. Non basta il
ruolo: se non sei in quel progetto, non ci sei dentro.

## I ruoli in un progetto

Sono tre e si assegnano progetto per progetto. La stessa persona puo' essere
responsabile di un progetto e semplice lettore di un altro.

| Ruolo | Che cosa fa |
|---|---|
| project manager | governa il progetto: avanza le fasi, decide le richieste, vede tutto del suo progetto |
| ingegnere | ci lavora: carica documenti, aggiorna revisioni |
| lettore | consulta e basta |

Accanto a questi c'e' il **creatore**, che non e' un ruolo di progetto ma di
tutto il programma: amministra Aurora, e vede tutto.

## Le classificazioni

Ogni documento ne ha una, e sceglierla e' il modo in cui si decide chi lo
vedra'.

| Classificazione | Che cosa ci va |
|---|---|
| Tecnico | schemi, disegni, distinte, relazioni di prova, firmware |
| Commerciale | offerte, listini, ordini, corrispondenza commerciale |
| Qualita' | piani della qualita', non conformita', rapporti di audit |
| Amministrativo | contratti, accordi di riservatezza, documenti di spesa |
| Corrispondenza | i messaggi di posta archiviati e i loro allegati |

L'elenco non e' fisso: chi amministra Aurora puo' aggiungerne, rinominarle e
riordinarle dalla pagina **Permessi**.

## La griglia dei permessi

L'incrocio fra i tre ruoli e le classificazioni e' una griglia di caselle, e in
ogni casella ci sono tre spunte: **vedere**, **caricare**, **modificare**.

Quella griglia si amministra dall'interfaccia, e cambiarla ha effetto subito su
tutti - non serve che nessuno esca e rientri. Ogni casella cambiata lascia una
riga nel registro, con il valore di prima e quello di dopo: la domanda *"che
cosa poteva vedere un ingegnere il 3 marzo?"* ha una risposta.

Il punto di partenza, quello che Aurora si porta appresso appena installata, e'
questo:

| Ruolo | Tecnico | Commerciale | Qualita' | Amministrativo | Corrispondenza |
|---|---|---|---|---|---|
| project manager | tutto | tutto | tutto | tutto | tutto |
| ingegnere | tutto | niente | tutto | solo vedere | vede e corregge |
| lettore | solo vedere | niente | niente | niente | solo vedere |

## Perche' una pagina dice "non trovato" invece di "non puoi"

Se apri l'indirizzo di un documento che non ti riguarda, Aurora risponde che
non esiste. E' voluto: rispondere "esiste ma non puoi vederlo" direbbe a chi
prova che quel documento esiste, e su un'offerta a un cliente quella e' gia'
un'informazione.

Se invece il documento lo vedi gia' e ti manca solo il permesso per
un'operazione - caricare, cambiare stato - la risposta e' diversa e lo dice
chiaramente: non c'e' niente da nascondere a chi sta gia' guardando.

## La posta segue la stessa regola

Un messaggio archiviato **e' un documento di classificazione "Corrispondenza"**
nel progetto della versione a cui e' attaccato. Non c'e' nessuna seconda regola
e nessuna seconda griglia da tenere allineata: chi vede la corrispondenza di
quel progetto vede quel messaggio.

L'unica eccezione e' la quarantena, e ha una ragione: un messaggio non ancora
attribuito non e' in nessun progetto, quindi non c'e' nessuna regola che possa
dire chi lo vede. Vedi [Messaggi in quarantena](/aiuto/messaggi-in-quarantena).
