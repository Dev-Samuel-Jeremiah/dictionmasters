# Britfone data notice

`britfone.main.3.0.1.csv` is the main British English IPA dataset from
[Jose Llarena's Britfone project](https://github.com/JoseLlarena/Britfone).
The upstream project documents the comma-separated word/transcription format;
IPA units are separated by spaces, numbered rows represent pronunciation
variants, and underscores mark word boundaries. The application joins IPA units. It then
uses the upstream documented traditional equivalents for this site's chart:
Britfone /ɐ ɹ ɛ/ becomes /ʌ r e/. IPA-Dict's /ɐ/ is treated as a weak vowel
and shown as /ə/, or /ʌ/ when marked stressed. Stress marks are placed before
a known syllable onset when that onset is unambiguous. Vowel length,
diphthongs, and other source distinctions are retained.

Britfone is distributed under the MIT License. Keep the accompanying
`LICENSE.txt` with this dataset when redistributing it. No commercial
dictionary data is included.
