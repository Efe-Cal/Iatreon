package tui

import (
	"strings"

	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type legalDocument struct {
	title string
	body  string
}

type legalModel struct {
	document int
	viewport viewport.Model
	width    int
	height   int
	close    bool
}

var legalDocuments = []legalDocument{
	{title: "Terms of Service", body: termsOfService},
	{title: "Privacy Policy", body: privacyPolicy},
	{title: "Medical Disclaimer", body: medicalDisclaimer},
}

var legalPanelStyle = lipgloss.NewStyle().
	Border(lipgloss.NormalBorder()).
	BorderForeground(colorBorder)

func newLegalModel() legalModel {
	return legalModel{viewport: viewport.New(0, 0)}
}

func (m legalModel) Init() tea.Cmd { return nil }

func (m *legalModel) SetSize(w, h int) {
	m.width, m.height = w, h
	innerW := max(1, w-legalPanelStyle.GetHorizontalFrameSize())
	innerH := max(1, h-legalPanelStyle.GetVerticalFrameSize())
	m.viewport.Width = innerW
	m.viewport.Height = max(1, innerH-3)
	m.refresh()
}

func (m *legalModel) refresh() {
	m.viewport.SetContent(renderReportMarkdown(legalDocuments[m.document].body, m.viewport.Width))
}

func (m legalModel) footer() []string {
	return []string{"Left/Right Document", "Up/Down Scroll", "g/G Top/Bottom", "Esc Settings", "Ctrl+C Quit"}
}

func (m legalModel) Update(msg tea.Msg) (legalModel, tea.Cmd) {
	if key, ok := msg.(tea.KeyMsg); ok {
		switch key.String() {
		case "esc":
			m.close = true
			return m, nil
		case "tab", "right":
			m.document = (m.document + 1) % len(legalDocuments)
			m.viewport.GotoTop()
			m.refresh()
			return m, nil
		case "shift+tab", "left":
			m.document = (m.document - 1 + len(legalDocuments)) % len(legalDocuments)
			m.viewport.GotoTop()
			m.refresh()
			return m, nil
		case "g":
			m.viewport.GotoTop()
			return m, nil
		case "G":
			m.viewport.GotoBottom()
			return m, nil
		}
	}

	var cmd tea.Cmd
	m.viewport, cmd = m.viewport.Update(msg)
	return m, cmd
}

func (m legalModel) View() string {
	if m.width == 0 {
		return ""
	}

	tabs := make([]string, len(legalDocuments))
	for i, document := range legalDocuments {
		label := "  " + document.title + "  "
		style := lipgloss.NewStyle().Foreground(colorMuted)
		if i == m.document {
			label = "[ " + document.title + " ]"
			style = style.Bold(true).Foreground(colorPrimary)
		}
		tabs[i] = style.Render(label)
	}

	innerW := max(1, m.width-legalPanelStyle.GetHorizontalFrameSize())
	innerH := max(1, m.height-legalPanelStyle.GetVerticalFrameSize())
	content := lipgloss.JoinVertical(
		lipgloss.Left,
		settingsSectionStyle.Width(innerW).Render(legalDocuments[m.document].title),
		strings.Join(tabs, " "),
		"",
		m.viewport.View(),
	)
	return legalPanelStyle.Width(innerW).Height(innerH).Render(content)
}

const termsOfService = `# Terms of Service

**Effective date: July 26, 2026**

> Important: Iatreon is experimental software. It is not a medical device, health-care provider, emergency service, or substitute for professional care.

## 1. Agreement

These Terms govern your use of Iatreon. By creating an account or using the service, you agree to these Terms and the Privacy Policy. If you do not agree, do not use Iatreon.

## 2. Eligibility

You must be at least 18 years old and legally able to enter this agreement. Iatreon is not directed to children.

## 3. What Iatreon Provides

Iatreon uses artificial intelligence and public medical literature to help you organize health information, explore questions, and generate possible research, assessment, and differential-diagnosis material. Outputs are informational and may be incomplete, outdated, biased, or wrong.

## 4. No Medical Care or Emergency Use

Iatreon does not provide medical advice, diagnosis, treatment, prescriptions, or a clinician-patient relationship. Do not rely on it to make or delay health-care decisions. Confirm all outputs with a qualified clinician.

Do not use Iatreon for emergencies. If you believe someone may be in danger, contact local emergency services immediately.

## 5. Your Account and Responsibilities

Keep your credentials and provider API keys secure. You are responsible for activity under your account and for the accuracy and lawfulness of information you submit. Do not submit another person's health information unless you have authority and any required consent.

You must not misuse the service, interfere with its operation, attempt unauthorized access, upload malicious content, violate law or third-party rights, or use outputs to harm, discriminate against, or make high-impact decisions about another person.

## 6. Third-Party Services and Content

Depending on your settings, requests may be processed by Iatreon infrastructure, Hack Club AI, Cloudflare, public literature sources, or an AI/search provider you select. Those services have their own terms and privacy practices. Iatreon does not control or endorse third-party content, models, citations, or availability.

## 7. Software and Intellectual Property

Iatreon and its components are protected by applicable intellectual-property laws and any licenses distributed with the software. These Terms do not grant rights beyond those licenses. You retain rights in content you submit, subject to the limited permission needed to process it and provide the service.

## 8. Availability and Changes

The service may change, fail, or be discontinued without guarantee. We may update these Terms by posting a revised version and date. Continued use after an update means you accept the revised Terms where permitted by law.

## 9. Suspension and Termination

Access may be limited or terminated for misuse, security risk, legal requirements, or material breach. You may stop using Iatreon at any time. Uninstalling the app does not necessarily delete backend account records or cloud backups.

## 10. Disclaimers

TO THE MAXIMUM EXTENT PERMITTED BY LAW, IATREON IS PROVIDED "AS IS" AND "AS AVAILABLE," WITHOUT WARRANTIES OF ACCURACY, RELIABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, OR UNINTERRUPTED OPERATION. Nothing in these Terms excludes a warranty or right that cannot lawfully be excluded.

## 11. Limitation of Liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, IATREON'S OPERATORS AND CONTRIBUTORS WILL NOT BE LIABLE FOR INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, EXEMPLARY, OR PUNITIVE DAMAGES, LOSS OF DATA, OR HARM ARISING FROM RELIANCE ON AI OUTPUTS OR THIRD-PARTY SERVICES. Liability that cannot lawfully be excluded remains unaffected.

## 12. General

If a provision is unenforceable, the remainder stays effective. Failure to enforce a provision is not a waiver. These Terms are the entire agreement about the service unless a separate written agreement applies.

## 13. Contact

For legal or support questions, open a non-confidential issue at https://github.com/Efe-Cal/Iatreon/issues. Never include health information, passwords, or API keys in a public issue.
`

const privacyPolicy = `# Privacy Policy

**Effective date: July 26, 2026**

This policy explains how Iatreon handles information. Iatreon is designed to keep sensitive working data in an encrypted local database, but some features send data to external services.

## 1. Information Handled

- **Account data:** username, salted password hash, account identifier, authentication-token records, and account creation time.
- **Health and conversation data:** demographics, history, medications, allergies, symptoms, social and family history, chat transcripts, research, and generated assessments.
- **Provider settings:** selected providers, models, endpoints, and API credentials.
- **Backup data:** an optional encrypted copy of the local database, plus backup identifier, checksum, owner, object location, and creation time.
- **Research job data:** requested article or PDF URLs, job identifiers, and retrieved public literature.
- **Technical data:** network and application error information ordinarily produced when operating the service. Iatreon does not include an advertising or analytics SDK in the reviewed client code.

## 2. Where Information Goes

Health data, chats, provider settings, credentials, and session tokens are stored in an encrypted SQLCipher database on your device. The encryption key is managed separately by the operating system's credential storage.

When you use AI features, the prompt and relevant health or conversation context are sent to the configured AI provider. With Iatreon AI, requests pass through Iatreon's authenticated proxy and are forwarded to Hack Club AI. If you choose another provider, the client sends requests to that provider or endpoint using your credentials.

Research features contact public literature and search services. PDF features send an article URL to Iatreon's PDF service, which downloads and processes the retrieved document.

Cloud backup is optional. When you select it, the encrypted database is uploaded to Cloudflare R2. Iatreon's backend stores backup metadata. The backup remains encrypted, but anyone with the local encryption key and backup file may be able to read it.

## 3. Why Information Is Used

Information is used to create and secure accounts; provide AI, research, history, profile, and backup features; maintain and troubleshoot the service; prevent abuse; and comply with law. Iatreon does not claim to sell personal information or use health information for targeted advertising.

Where data-protection law requires a legal basis, processing may be necessary to provide the service you request, based on your explicit choices for sensitive-data features, necessary for security and service operation, or required by law. The applicable basis depends on your location and use.

## 4. Sharing

Information may be disclosed to the providers described above, to infrastructure vendors acting for Iatreon, when you direct a disclosure, to protect users or the service, or when legally required. A provider you configure processes data under its own terms. Avoid sending information you do not want that provider to receive.

## 5. Retention and Deletion

Local records remain until you remove them or the local database. Authentication and backup metadata remain on Iatreon's backend while needed to provide and secure those features or satisfy legal obligations. Encrypted backups remain in cloud storage until deleted under the applicable account or operational process.

The current client does not provide a complete in-app account-deletion workflow. To request access, correction, deletion, restriction, or a copy of backend data, use the contact method below. Do not include health information in a public request. Requests may require identity verification and are subject to applicable exceptions.

## 6. Security

Iatreon uses encrypted local storage, salted password hashing, authenticated sessions, access controls, encrypted backups, and integrity checks. No system is perfectly secure. Protect your device, credentials, local encryption key, provider keys, and backups.

## 7. International Processing

Providers may process information in countries other than yours, where privacy protections may differ. Review the location and terms of each provider you select.

## 8. Your Choices and Rights

You can choose providers and whether to create a cloud backup. Depending on your location, you may have rights to be informed, access, correct, delete, restrict, object, withdraw consent, receive portable data, or complain to a data-protection authority. Some rights are limited by law and technical feasibility.

## 9. Children

Iatreon is not intended for anyone under 18. Do not submit a child's personal or health information.

## 10. HIPAA and Health-Data Laws

Using a health app does not by itself make the app subject to HIPAA. Unless a separate written agreement says otherwise, do not use Iatreon as a HIPAA business associate or to process regulated clinical records on behalf of a covered entity. Other consumer health privacy and breach-notification laws may still apply.

## 11. Changes

This policy may change as the product, providers, or law changes. The effective date above identifies the current version.

## 12. Contact

Open a non-confidential issue at https://github.com/Efe-Cal/Iatreon/issues and request a private contact channel. Never post health information, passwords, tokens, or API keys in a public issue.
`

const medicalDisclaimer = `# Medical and AI Disclaimer

**Effective date: July 26, 2026**

## Not Medical Advice

Iatreon provides experimental, AI-generated information for education and research. It is not a doctor, medical device, diagnostic service, treatment service, pharmacy, or substitute for a qualified health professional. Use of Iatreon does not create a clinician-patient relationship.

## Emergency Warning

Do not use Iatreon for an emergency or time-sensitive condition. If you think you or someone else may be in danger, contact local emergency services now. Do not wait for an Iatreon response.

## AI Limitations

AI systems can fabricate facts and citations, misunderstand context, omit important conditions, reflect bias, and provide unsafe or outdated suggestions. A confident or detailed answer is not proof that it is correct. Source links may be incomplete, mismatched, or unavailable.

## Your Responsibility

Always seek advice from a qualified clinician who can examine you and review your complete history. Do not start, stop, or change medication, testing, diet, or treatment based only on Iatreon. Never delay professional care because of an output.

Provide complete and accurate information, but share only information you are authorized to disclose. Iatreon cannot account for facts you omit, measurements it cannot verify, or changes in your condition.

## Research and Assessments

Differential diagnoses and research reports describe possibilities, not confirmed diagnoses. They may not cover every cause or apply to your circumstances. Citations and medical literature do not replace individualized clinical judgment.

## No Guarantee

Iatreon does not guarantee accuracy, safety, completeness, availability, outcomes, or fitness for any medical purpose. You assume the risk of using experimental outputs, subject to rights that applicable law does not allow you to waive.
`
