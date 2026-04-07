# Resume Tailoring Workflow

This is the autonomous 7-step workflow Claude follows when asked to tailor a resume.

## Inputs
- `JOB_DESCRIPTION` — pulled from DynamoDB via `get_job_details` tool
- `MASTER_RESUME` — read from Google Drive: file named `Donnelly_Bryan_Resume_master` in folder `1CCY1NFNnoeylWDtEBQ3rv2UCofcoCKIh`
- `COMPANY_NAME` and `JOB_TITLE` — from the job record, used for output file naming

## Output
- Google Doc titled `[COMPANY_NAME] — [JOB_TITLE] — Tailored Resume` saved to the same Drive folder
- Email to donnelly.bryand@gmail.com with a link to the doc and job summary

---

## Step 1: Job Description Analysis

Analyze the job description and extract:
- Key responsibilities, skills, and competencies
- Implied skills not explicitly listed
- Employer's expectations for success based on phrasing
- Industry-specific terms that align with transferable skills
- Tone and emphasis (technical, stakeholder-facing, facilitation-focused, etc.)

If a prior tailored resume for this company exists in the Drive folder, note it as a reference point. Always use `MASTER_RESUME` as the working base.

---

## Step 2: Resume Audit — Remove Weakly Relevant Content

Review `MASTER_RESUME` against the job description and flag for removal:
1. Least relevant bullets that don't strongly align with the role or are redundant
2. Weak job sections, Core Competencies, or Technical Proficiencies that add little value
3. Irrelevant tools not useful in this role

Strict rules:
- Use `MASTER_RESUME` verbatim — do not paraphrase or rewrite content here
- Do not remove K-12 tools from Technical Proficiencies unless they appear after the word "Comparable"
- Audit Core Competencies (located below job title, above Professional Summary)
- Ignore the Professional Summary in this step

Apply the removals to produce a trimmed working draft.

---

## Step 3: Extract ATS Keywords

Extract all ATS keywords from the job description. Do not compare against the resume yet.

---

## Step 4: Compare ATS Keywords Against Resume

Compare the extracted keywords from Step 3 against the trimmed working draft. Produce one full table covering the entire resume (excluding Professional Summary) with columns: Keyword | Present | Section.

Strict rules:
- Match only what is literally present — zero inference, zero synonym mapping, zero guesswork
- No bold font
- Process order: Core Competencies → each job experience section → Technical Skills

End with:
- Total Keywords Present: [#]
- Total Keywords Missing: [#]

---

## Step 4b: Keyword Insertion and Swap

Identify where missing keywords can be inserted or swapped in with minimal revision. Present as complete before/after sentences organized by section, noting which term(s) were added. Sections to cover: Core Competencies, Professional Summary, Work Experience, Additional Experience, Technical Proficiencies.

Rules:
- Natural insertions only — no forced or nonsensical keyword cramming
- Swaps should replace less relevant terms, not stack on top

Apply the insertions to the working draft.

---

## Step 5: Bullet Refinement

Analyze and refine resume bullets for:
- Clearer alignment with the job
- Stronger industry-standard phrasing without forcing keywords unnaturally
- Accurate positioning of transferable skills
- Flag any JD-listed programs missing from the resume

Strict rules:
- Do not introduce new experiences — only reword existing bullets
- Do not remove ATS keywords in the process of rewording

Apply the refinements to the working draft.

---

## Step 6: Professional Summary and Cover Letter

Generate a Professional Summary and a Cover Letter.

**Professional Summary:**
- 3-5 sentences, approximately 50-75 words
- Highlight the most relevant skills and experience for this specific role
- Showcase ability to connect with people and collaborate effectively
- Sound natural, not AI-generated

**Cover Letter:**
- No keyword cramming, no clichés, no pandering to the company
- 2-3 bullets, one highlighting a soft skill from the JD
- Salutation: "Greetings Talent Acquisition Team" with today's date above it
- Sound like a normal human wrote it

Strict rules:
- Do not use the word "Mindset"
- Do not fabricate experience or claims
- No long em dashes
- No bold font
- Normal bullets only (not images or symbols)

---

## Step 7: Final Proofread

Conduct a final proofread for spelling, grammar, and clarity only.

Strict rules:
- No paraphrasing or wording changes — correct errors only
- Do not alter meaning

---

## Delivery

1. Save the completed tailored resume and cover letter as a Google Doc titled:
   `[COMPANY_NAME] — [JOB_TITLE] — Tailored Resume`
   in Drive folder: `1CCY1NFNnoeylWDtEBQ3rv2UCofcoCKIh`

2. Send an email to `donnelly.bryand@gmail.com` with:
   - Subject: `Tailored Resume Ready — [JOB_TITLE] at [COMPANY_NAME]`
   - Body: job title, company, AI score, AI verdict, match reasons, and a link to the Drive doc
