# Glossario

I termini che compaiono in Aurora, spiegati in italiano semplice. In ordine
alfabetico.

## Archivio

La cartella sul disco del server dove Aurora deposita il contenuto dei file
caricati. I file ci stanno con un nome che e' una lunga sequenza di lettere e
cifre - l'impronta del contenuto - e non con il loro nome originale, che sta
invece nel database. E' quello che permette a due documenti con lo stesso
allegato di occupare un file solo.

## Audit trail

Vedi **Registro delle operazioni**.

## Classificazione

L'etichetta che dice **di che genere** e' un documento: Tecnico, Commerciale,
Qualita', Amministrativo, Corrispondenza. E' quella che decide chi lo puo'
vedere. Vedi [Chi vede che cosa](/aiuto/chi-vede-che-cosa).

## Codice prodotto

Il codice con cui l'azienda chiama un apparecchio, per esempio
`RMS1100-24-110SW`. E' un **codice parlante**: dentro ci sono il modello, la
potenza, la tensione d'ingresso, quella d'uscita e la variante, e Aurora lo
scompone per poterci cercare sopra.

La regola con cui lo scompone non e' scritta dentro il programma: sta in un file
di configurazione, e si cambia senza toccare Aurora. Un codice che non si
scompone viene **accettato lo stesso**, con una segnalazione: un codice fuori
regola e' comunque un prodotto che esiste.

## Creatore

Il ruolo di chi amministra Aurora: crea gli utenti, decide i permessi, gestisce
le classificazioni e le fasi, vede tutto. Non e' un ruolo di progetto: vale su
tutto il programma.

## CSRF

Una protezione tecnica dei moduli. Ogni modulo di Aurora porta con se' un
gettone nascosto, e senza quel gettone la richiesta viene rifiutata. Serve a
impedire che una pagina ostile aperta in un'altra scheda del browser faccia
compiere un'operazione a tuo nome. Se compare "richiesta non valida", di solito
basta ricaricare la pagina e rifare l'operazione.

## Fase

Uno dei passi del percorso che un progetto attraversa: "Concept",
"Feasibility", "Development". Le fasi non sono scritte dentro il programma: si
scelgono e si cambiano dalla pagina **Fasi**. Vedi
[Far avanzare un progetto](/aiuto/far-avanzare-un-progetto).

## Impronta (SHA-256)

Una sequenza di 64 lettere e cifre calcolata sul contenuto di un file. Due file
identici hanno la stessa impronta; cambiando anche un solo byte, l'impronta
cambia completamente. Aurora la usa per due cose: per non salvare due volte lo
stesso contenuto, e per accorgersi se qualcosa nel registro delle operazioni e'
stato toccato.

## Modello di fasi

Il percorso completo, cioe' l'elenco ordinato delle fasi che un progetto
attraversera'. Se ne possono avere piu' d'uno - uno per lo sviluppo, uno per le
personalizzazioni - e si sceglie quando si apre il progetto.

Un modello **non si modifica** dopo essere stato usato: se ne crea una versione
nuova. I progetti gia' aperti continuano con il percorso con cui erano nati.

## Progetto

Il lavoro che si fa su una versione di prodotto. Ha un responsabile, una
squadra, delle norme di riferimento e un percorso di fasi. I documenti stanno
dentro un progetto.

## Quarantena

L'elenco dei messaggi di posta che Aurora ha archiviato ma non e' riuscita ad
attribuire a un prodotto. Vedi
[Messaggi in quarantena](/aiuto/messaggi-in-quarantena).

## Registro delle operazioni

L'elenco di tutto quello che e' successo dentro Aurora: chi e' entrato, chi ha
caricato che cosa, chi ha cambiato un permesso, chi ha scaricato un documento.
Ogni riga dice chi, che cosa, quando, da quale calcolatore, e una frase in
italiano che si capisce senza conoscere il programma.

**Il registro si scrive e non si tocca piu'.** Non e' una buona intenzione: il
database stesso rifiuta di modificarne o cancellarne una riga, e ogni voce
porta l'impronta di quella precedente, cosi' una manomissione fatta scavalcando
il programma si vede.

## Ritirare

Togliere un documento dagli elenchi senza cancellarlo. E' l'unico modo che
Aurora ha di "cancellare" qualcosa: la riga resta, il file resta, e chi
amministra puo' rimettere tutto a posto.

## Sessione

Il periodo in cui il browser resta riconosciuto dopo che hai scritto le
credenziali. Chiudendo il browser la sessione finisce; con "Ricordami" resta
valida piu' a lungo, su quel calcolatore.

Da "Esci da tutti i dispositivi", nella pagina iniziale, si chiudono tutte le
sessioni aperte a proprio nome: e' quello che si fa quando ci si accorge di
aver lasciato Aurora aperta su un altro computer.

## Stato

Vedi [Versioni e stati](/aiuto/versioni-e-stati). In Aurora ce ne sono due
famiglie: gli stati del **ciclo di vita** di una versione di prodotto, e gli
stati di un **documento**.

## Versione di prodotto

Una revisione dell'apparecchio. Non va confusa con la versione di un documento,
che e' la revisione di un file. Vedi
[Versioni e stati](/aiuto/versioni-e-stati).
