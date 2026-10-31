# outputs/interface/

[`index.html`](index.html) is **the AI at 70 app**: the clinician's web page. It needs the server behind it, so opening the file directly shows "Can't reach the AI at 70 server".

```bash
source .venv/bin/activate
python scripts/run_ai_at_70.py      # then open http://localhost:5070
```

## The steps

| Step | What the clinician does | Screenshot |
|---|---|---|
| Landing | Start a visit, or open the patient check-in form | [1_landing.png](screenshots/1_landing.png) |
| Check-in form | The patient answers a few simple questions and exports JSON (from [`tools/questionnaire/`](../../tools/questionnaire/)) | [2_checkin_form.png](screenshots/2_checkin_form.png) |
| 1. Check-in | Upload the patient's check-in, which sets the language and who may get the summary | (shown in the next screenshot's banner) |
| 2. Conversation | Record the visit, upload audio, or paste a transcript; it's optional but adds helpful detail (**Skip** is there too) | [3_conversation.png](screenshots/3_conversation.png) |
| 3. Clinician note | Type, paste or upload the typed note (.txt or .pdf; a photo also works on macOS); add your name and the office phone | [4_clinician_note.png](screenshots/4_clinician_note.png) |
| 4. Review and approve | The patient's page on the left (Patient view / Show changes; click a sentence to edit it) and your checklist on the right (**Select all**); language buttons; approve with your name | [5_review.png](screenshots/5_review.png) |
| 5. Print, email, call | **Printout** (large print), **Email** (a draft to the patient or a consenting family member), or **Phone call** (the script, played in a natural voice) | [6_printout.png](screenshots/6_printout.png), [7_email.png](screenshots/7_email.png), [8_phone_call.png](screenshots/8_phone_call.png) |
| Another language | Spanish, Mandarin, Portuguese or Arabic for all three outputs; this needs a new approval | [9_spanish.png](screenshots/9_spanish.png) |

The automatic checks sit in a dropdown under the send tabs:

- reading level
- everyday talk
- every medicine listed
- numbers kept
- anything left out
- sources

The page is self-contained HTML, CSS and JavaScript (fonts from Google Fonts). It calls the server's `/api/...` endpoints, listed in [`scripts/README.md`](../../scripts/README.md).
