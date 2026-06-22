from spellchecker import SpellChecker
spell = SpellChecker()
q = "ADP WFN prerequistes config"
words = q.split()
corrected = []
for w in words:
    clean_w = ''.join(c for c in w if c.isalpha())
    if len(clean_w) > 4 and not clean_w.isupper():
        c = spell.correction(clean_w)
        if c and c != clean_w.lower():
            corrected.append(c)
print(q + " " + " ".join(corrected))
