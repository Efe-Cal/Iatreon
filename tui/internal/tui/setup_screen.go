package tui

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// setupStep enumerates the wizard pages.
type setupStep int

const (
	stepLanding setupStep = iota
	stepAge
	stepGender
	stepPMH
	stepMedications
	stepAllergies
	stepFamilyHistory
	stepSmoking
	stepAlcohol
	stepExercise
	stepConfirm
)

type setupModel struct {
	step       setupStep
	userid     string
	sessionKey *SessionKey
	width      int
	height     int

	// Form fields
	age         textinput.Model
	gender      textinput.Model
	pmh         textinput.Model
	medications textinput.Model
	allergies   textinput.Model
	familyHist  textinput.Model
	smoking     textinput.Model
	alcohol     textinput.Model
	exercise    textinput.Model

	// Multi-line buffers for textarea-like fields (comma-separated)
	pmhLines         []string
	medicationsLines []string
	allergiesLines   []string
	familyHistLines  []string

	err        error
	submitted  bool
	submitting bool

	headerText    string
	footerActions []string
}

func (m *setupModel) SetHeader(h string)   { m.headerText = h }
func (m *setupModel) SetFooter(a []string) { m.footerActions = a }
func (m setupModel) GetHeader() string     { return m.headerText }
func (m setupModel) GetFooter() []string   { return m.footerActions }

func newSetupModel(userid string, sessionKey *SessionKey) setupModel {
	// Age input
	age := textinput.New()
	age.Placeholder = "e.g. 35"
	age.CharLimit = 3
	age.Width = 10
	age.Validate = func(s string) error { return nil }

	gender := textinput.New()
	gender.Placeholder = "e.g. Male, Female, Non-binary"
	gender.CharLimit = 32
	gender.Width = 30

	// Multi-line inputs initialized as textinput for the prompt line
	pmh := textinput.New()
	pmh.Placeholder = "Type one condition and press Enter (empty to finish)"
	pmh.CharLimit = 128
	pmh.Width = 50

	medications := textinput.New()
	medications.Placeholder = "Type one medication and press Enter (empty to finish)"
	medications.CharLimit = 128
	medications.Width = 50

	allergies := textinput.New()
	allergies.Placeholder = "Type one allergy and press Enter (empty to finish)"
	allergies.CharLimit = 128
	allergies.Width = 50

	familyHist := textinput.New()
	familyHist.Placeholder = "Type one condition and press Enter (empty to finish)"
	familyHist.CharLimit = 128
	familyHist.Width = 50

	smoking := textinput.New()
	smoking.Placeholder = "e.g. Never, Former (quit 5 years ago), Current (1 pack/day)"
	smoking.CharLimit = 64
	smoking.Width = 50

	alcohol := textinput.New()
	alcohol.Placeholder = "e.g. Never, Occasional, 2 drinks/week"
	alcohol.CharLimit = 64
	alcohol.Width = 50

	exercise := textinput.New()
	exercise.Placeholder = "e.g. Sedentary, 3x/week jogging, Daily walking"
	exercise.CharLimit = 64
	exercise.Width = 50

	age.Focus()

	return setupModel{
		step:             stepLanding,
		userid:           userid,
		sessionKey:       sessionKey,
		age:              age,
		gender:           gender,
		pmh:              pmh,
		medications:      medications,
		allergies:        allergies,
		familyHist:       familyHist,
		smoking:          smoking,
		alcohol:          alcohol,
		exercise:         exercise,
		pmhLines:         []string{},
		medicationsLines: []string{},
		allergiesLines:   []string{},
		familyHistLines:  []string{},
	}
}

func (m *setupModel) SetSize(w, h int) {
	m.width = w
	m.height = h
	fieldWidth := w/2 + 10
	if fieldWidth < 30 {
		fieldWidth = 30
	}
	if fieldWidth > 60 {
		fieldWidth = 60
	}
	m.age.Width = min(10, fieldWidth)
	m.gender.Width = fieldWidth
	m.pmh.Width = fieldWidth
	m.medications.Width = fieldWidth
	m.allergies.Width = fieldWidth
	m.familyHist.Width = fieldWidth
	m.smoking.Width = fieldWidth
	m.alcohol.Width = fieldWidth
	m.exercise.Width = fieldWidth
}

func (m setupModel) Init() tea.Cmd {
	return textinput.Blink
}

type profileSubmittedMsg struct {
	err error
}

func submitProfile(userid string, m setupModel) tea.Cmd {
	return func() tea.Msg {
		body := map[string]interface{}{
			"user_id": userid,
			"demographics": map[string]string{
				"age":    m.age.Value(),
				"gender": m.gender.Value(),
			},
			"pmh":            m.pmhLines,
			"medications":    m.medicationsLines,
			"allergies":      m.allergiesLines,
			"family_history": m.familyHistLines,
			"social": map[string]string{
				"smoking":  m.smoking.Value(),
				"alcohol":  m.alcohol.Value(),
				"exercise": m.exercise.Value(),
			},
		}

		jsonData, err := json.Marshal(body)
		if err != nil {
			return profileSubmittedMsg{err: err}
		}

		req, err := http.NewRequest(http.MethodPost, "http://localhost:8000/user-profile", bytes.NewReader(jsonData))
		if err != nil {
			return profileSubmittedMsg{err: err}
		}
		req.Header.Set("Content-Type", "application/json")
		addSessionKeyHeader(req, m.sessionKey.Get())

		resp, err := sharedHTTPDo(req)
		if err != nil {
			return profileSubmittedMsg{err: err}
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			return profileSubmittedMsg{err: fmt.Errorf("server returned status: %d %s", resp.StatusCode, resp.Status)}
		}

		return profileSubmittedMsg{}
	}
}

func (m setupModel) Update(msg tea.Msg) (setupModel, tea.Cmd) {
	if m.submitting {
		switch msg := msg.(type) {
		case profileSubmittedMsg:
			m.submitting = false
			if msg.err != nil {
				m.err = msg.err
				return m, nil
			}
			m.submitted = true
			return m, nil
		default:
			return m, nil
		}
	}

	switch msg := msg.(type) {
	case tea.KeyMsg:
		key := msg.String()

		// Landing page: any key advances to first field.
		if m.step == stepLanding {
			if key == "ctrl+c" {
				return m, tea.Quit
			}
			m.step = stepAge
			m.age.Focus()
			return m, textinput.Blink
		}

		// Multi-line collection steps (pmh, medications, allergies, family_history)
		if m.isMultiLineStep() {
			return m.updateMultiLineStep(msg)
		}

		// Single-line field steps
		switch key {
		case "enter":
			return m.advanceStep()
		case "esc":
			return m.goBack()
		case "ctrl+c":
			return m, tea.Quit
		}

	case error:
		m.err = msg
	}

	// Forward update to the active textinput
	var cmd tea.Cmd
	switch m.step {
	case stepAge:
		m.age, cmd = m.age.Update(msg)
	case stepGender:
		m.gender, cmd = m.gender.Update(msg)
	case stepSmoking:
		m.smoking, cmd = m.smoking.Update(msg)
	case stepAlcohol:
		m.alcohol, cmd = m.alcohol.Update(msg)
	case stepExercise:
		m.exercise, cmd = m.exercise.Update(msg)
	}
	return m, cmd
}

func (m *setupModel) isMultiLineStep() bool {
	return m.step == stepPMH || m.step == stepMedications ||
		m.step == stepAllergies || m.step == stepFamilyHistory
}

func (m *setupModel) currentLines() *[]string {
	switch m.step {
	case stepPMH:
		return &m.pmhLines
	case stepMedications:
		return &m.medicationsLines
	case stepAllergies:
		return &m.allergiesLines
	case stepFamilyHistory:
		return &m.familyHistLines
	}
	return nil
}

func (m *setupModel) currentInput() *textinput.Model {
	switch m.step {
	case stepPMH:
		return &m.pmh
	case stepMedications:
		return &m.medications
	case stepAllergies:
		return &m.allergies
	case stepFamilyHistory:
		return &m.familyHist
	}
	return nil
}

func (m *setupModel) updateMultiLineStep(msg tea.KeyMsg) (setupModel, tea.Cmd) {
	key := msg.String()

	if key == "esc" {
		// Clear current input and go back.
		m.currentInput().SetValue("")
		return m.goBack()
	}

	if key == "enter" {
		value := strings.TrimSpace(m.currentInput().Value())
		if value == "" {
			// Empty input = finish this step, advance.
			m.currentInput().SetValue("")
			return m.advanceStep()
		}
		// Append to list and clear input.
		lines := m.currentLines()
		*lines = append(*lines, value)
		m.currentInput().SetValue("")
		return *m, nil
	}

	// Forward typing to textinput.
	var cmd tea.Cmd
	input := m.currentInput()
	*input, cmd = input.Update(msg)
	return *m, cmd
}

func (m setupModel) advanceStep() (setupModel, tea.Cmd) {
	next := m.step + 1
	if next > stepConfirm {
		return m, nil
	}
	m.step = next

	// Set footer actions based on step type
	if m.step == stepConfirm {
		m.SetFooter([]string{"Enter Confirm", "Esc Back", "Ctrl+C Quit"})
	} else if m.isMultiLineStep() {
		m.SetFooter([]string{"Enter Add Item", "Enter(empty) Next", "Esc Back", "Ctrl+C Quit"})
	} else {
		m.SetFooter([]string{"Enter Continue", "Esc Back", "Ctrl+C Quit"})
	}

	// Focus the appropriate input for the new step.
	switch m.step {
	case stepAge:
		m.age.Focus()
	case stepGender:
		m.gender.Focus()
	case stepPMH:
		m.pmh.Focus()
	case stepMedications:
		m.medications.Focus()
	case stepAllergies:
		m.allergies.Focus()
	case stepFamilyHistory:
		m.familyHist.Focus()
	case stepSmoking:
		m.smoking.Focus()
	case stepAlcohol:
		m.alcohol.Focus()
	case stepExercise:
		m.exercise.Focus()
	case stepConfirm:
		// Submit on confirm step.
		m.submitting = true
		return m, submitProfile(m.userid, m)
	}
	return m, textinput.Blink
}

func (m setupModel) goBack() (setupModel, tea.Cmd) {
	if m.step == stepLanding {
		return m, nil
	}
	prev := m.step - 1
	if prev < stepLanding {
		prev = stepLanding
	}
	m.step = prev

	// Clear the current input when going back from a multi-line step
	switch m.step {
	case stepLanding:
		// nothing to focus
	case stepAge:
		m.age.Focus()
	case stepGender:
		m.gender.Focus()
	case stepPMH:
		m.pmh.Focus()
	case stepMedications:
		m.medications.Focus()
	case stepAllergies:
		m.allergies.Focus()
	case stepFamilyHistory:
		m.familyHist.Focus()
	case stepSmoking:
		m.smoking.Focus()
	case stepAlcohol:
		m.alcohol.Focus()
	case stepExercise:
		m.exercise.Focus()
	}
	return m, textinput.Blink
}

// ---- View ----

func (m setupModel) View() string {
	if m.submitted {
		return m.renderDone()
	}
	if m.submitting {
		return m.renderSubmitting()
	}

	switch m.step {
	case stepLanding:
		return m.renderLanding()
	default:
		return m.renderForm()
	}
}

func (m setupModel) renderLanding() string {
	subtitle := systemStyle.Render("Your AI-powered clinical assistant")

	boxStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(colorPrimary).
		Padding(2, 4).
		Margin(1, 0)

	features := []string{
		"🩺  Intelligent patient intake",
		"📚  Evidence-based research",
		"🧬  Differential diagnosis support",
		"🔒  End-to-end encrypted via SSH",
	}

	featureList := lipgloss.JoinVertical(lipgloss.Left, features...)
	box := boxStyle.Render(featureList)

	content := lipgloss.JoinVertical(
		lipgloss.Center,
		subtitle,
		"",
		box,
	)

	return lipgloss.Place(
		m.width, m.height,
		lipgloss.Center, lipgloss.Center,
		content,
	)
}

func (m setupModel) renderForm() string {
	stepLabel := m.stepLabel()
	subtitle := systemStyle.Render(fmt.Sprintf("Step %d of 10 — %s", m.stepNumber(), stepLabel))

	fieldContent := m.renderField()
	prompt := hintStyle.Render(m.stepPrompt())

	if m.err != nil {
		prompt = errorStyle.Render("Error: " + m.err.Error())
	}

	content := lipgloss.JoinVertical(
		lipgloss.Left,
		subtitle,
		"",
		fieldContent,
		"",
		prompt,
	)

	return lipgloss.Place(
		m.width, m.height,
		lipgloss.Center, lipgloss.Center,
		content,
	)
}

func (m setupModel) renderField() string {
	labelStyle := lipgloss.NewStyle().Bold(true).Foreground(colorPrimary)

	switch m.step {
	case stepAge:
		return lipgloss.JoinVertical(lipgloss.Left,
			labelStyle.Render("Age"),
			m.age.View(),
		)
	case stepGender:
		return lipgloss.JoinVertical(lipgloss.Left,
			labelStyle.Render("Gender"),
			m.gender.View(),
		)
	case stepPMH:
		return m.renderMultiLineField("Past Medical History", m.pmhLines, m.pmh.View())
	case stepMedications:
		return m.renderMultiLineField("Current Medications", m.medicationsLines, m.medications.View())
	case stepAllergies:
		return m.renderMultiLineField("Allergies", m.allergiesLines, m.allergies.View())
	case stepFamilyHistory:
		return m.renderMultiLineField("Family History", m.familyHistLines, m.familyHist.View())
	case stepSmoking:
		return lipgloss.JoinVertical(lipgloss.Left,
			labelStyle.Render("Smoking Status"),
			m.smoking.View(),
		)
	case stepAlcohol:
		return lipgloss.JoinVertical(lipgloss.Left,
			labelStyle.Render("Alcohol Use"),
			m.alcohol.View(),
		)
	case stepExercise:
		return lipgloss.JoinVertical(lipgloss.Left,
			labelStyle.Render("Exercise / Physical Activity"),
			m.exercise.View(),
		)
	case stepConfirm:
		return m.renderSummary()
	default:
		return ""
	}
}

func (m setupModel) renderMultiLineField(title string, lines []string, inputView string) string {
	labelStyle := lipgloss.NewStyle().Bold(true).Foreground(colorPrimary)
	itemStyle := lipgloss.NewStyle().Foreground(colorAccent).PaddingLeft(4)

	var sb strings.Builder
	sb.WriteString(labelStyle.Render(title))
	sb.WriteString("\n")
	sb.WriteString("\n")

	if len(lines) > 0 {
		for _, line := range lines {
			sb.WriteString(itemStyle.Render("• " + line))
			sb.WriteString("\n")
		}
		sb.WriteString("\n")
	}

	sb.WriteString(inputView)
	return sb.String()
}

func (m setupModel) renderSummary() string {
	labelStyle := lipgloss.NewStyle().Bold(true).Foreground(colorPrimary)
	itemStyle := lipgloss.NewStyle().Foreground(colorAccent).PaddingLeft(4)

	var sb strings.Builder
	sb.WriteString(labelStyle.Render("Review Your Profile"))
	sb.WriteString("\n")
	sb.WriteString("\n")
	sb.WriteString(systemStyle.Render("Demographics"))
	sb.WriteString("\n")
	sb.WriteString(itemStyle.Render(fmt.Sprintf("Age: %s", m.age.Value())))
	sb.WriteString("\n")
	sb.WriteString(itemStyle.Render(fmt.Sprintf("Gender: %s", m.gender.Value())))
	sb.WriteString("\n")
	sb.WriteString("\n")

	sb.WriteString(systemStyle.Render("Past Medical History"))
	sb.WriteString("\n")
	for _, s := range m.pmhLines {
		sb.WriteString(itemStyle.Render("• " + s))
		sb.WriteString("\n")
	}
	sb.WriteString("\n")

	sb.WriteString(systemStyle.Render("Medications"))
	sb.WriteString("\n")
	for _, s := range m.medicationsLines {
		sb.WriteString(itemStyle.Render("• " + s))
		sb.WriteString("\n")
	}
	sb.WriteString("\n")

	sb.WriteString(systemStyle.Render("Allergies"))
	sb.WriteString("\n")
	for _, s := range m.allergiesLines {
		sb.WriteString(itemStyle.Render("• " + s))
		sb.WriteString("\n")
	}
	sb.WriteString("\n")

	sb.WriteString(systemStyle.Render("Family History"))
	sb.WriteString("\n")
	for _, s := range m.familyHistLines {
		sb.WriteString(itemStyle.Render("• " + s))
		sb.WriteString("\n")
	}
	sb.WriteString("\n")

	sb.WriteString(systemStyle.Render("Social History"))
	sb.WriteString("\n")
	sb.WriteString(itemStyle.Render(fmt.Sprintf("Smoking: %s", m.smoking.Value())))
	sb.WriteString("\n")
	sb.WriteString(itemStyle.Render(fmt.Sprintf("Alcohol: %s", m.alcohol.Value())))
	sb.WriteString("\n")
	sb.WriteString(itemStyle.Render(fmt.Sprintf("Exercise: %s", m.exercise.Value())))

	return sb.String()
}

func (m setupModel) renderSubmitting() string {
	content := lipgloss.JoinVertical(
		lipgloss.Center,
		systemStyle.Render("Please wait while we set up your account."),
	)
	return lipgloss.Place(
		m.width, m.height,
		lipgloss.Center, lipgloss.Center,
		content,
	)
}

func (m setupModel) renderDone() string {
	content := lipgloss.JoinVertical(
		lipgloss.Center,
		systemStyle.Render("Your account is ready."),
		"",
		hintStyle.Render("Opening chat..."),
	)
	return lipgloss.Place(
		m.width, m.height,
		lipgloss.Center, lipgloss.Center,
		content,
	)
}

func (m setupModel) stepLabel() string {
	labels := map[setupStep]string{
		stepAge:           "Age",
		stepGender:        "Gender",
		stepPMH:           "Past Medical History",
		stepMedications:   "Current Medications",
		stepAllergies:     "Allergies",
		stepFamilyHistory: "Family History",
		stepSmoking:       "Smoking History",
		stepAlcohol:       "Alcohol Use",
		stepExercise:      "Physical Activity",
		stepConfirm:       "Review & Submit",
	}
	return labels[m.step]
}

func (m setupModel) stepNumber() int {
	return int(m.step)
}

func (m setupModel) stepPrompt() string {
	messages := map[setupStep]string{
		stepAge:           "Enter your age",
		stepGender:        "Enter your gender identity",
		stepPMH:           "Enter past conditions one at a time · Empty Enter to finish",
		stepMedications:   "Enter current medications one at a time · Empty Enter to finish",
		stepAllergies:     "Enter allergies one at a time · Empty Enter to finish",
		stepFamilyHistory: "Enter family conditions one at a time · Empty Enter to finish",
		stepSmoking:       "Describe your smoking history",
		stepAlcohol:       "Describe your alcohol consumption",
		stepExercise:      "Describe your physical activity level",
		stepConfirm:       "Press Enter to submit your profile",
	}
	return messages[m.step]

}
