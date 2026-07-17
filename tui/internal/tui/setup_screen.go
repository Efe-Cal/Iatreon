package tui

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

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

type setupFieldKind int

const (
	setupSingleLine setupFieldKind = iota
	setupMultiLine
	setupConfirm
)

type setupField struct {
	step   setupStep
	label  string
	prompt string
	input  *textinput.Model
	lines  *[]string
	kind   setupFieldKind
}

type setupModel struct {
	step       setupStep
	userid     string
	worker     *Worker
	canCancel  bool
	editing    bool
	width      int
	height     int
	listCursor int

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
	medicalSummary   string

	err        error
	cancelled  bool
	submitted  bool
	submitting bool
}

func newSetupModel(userid string, worker *Worker, canCancel bool) setupModel {
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
		worker:           worker,
		canCancel:        canCancel,
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

func newProfileEditor(userid string, worker *Worker, profile profileSettings) setupModel {
	m := newSetupModel(userid, worker, true)
	m.editing = true
	m.step = stepAge
	m.age.SetValue(profile.Demographics["age"])
	m.gender.SetValue(profile.Demographics["gender"])
	m.pmhLines = append([]string(nil), profile.PMH...)
	m.medicationsLines = append([]string(nil), profile.Medications...)
	m.allergiesLines = append([]string(nil), profile.Allergies...)
	m.familyHistLines = append([]string(nil), profile.FamilyHistory...)
	m.smoking.SetValue(profile.Social["smoking"])
	m.alcohol.SetValue(profile.Social["alcohol"])
	m.exercise.SetValue(profile.Social["exercise"])
	m.medicalSummary = profile.MedicalSummary
	m.focusCurrentField()
	return m
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
	for _, field := range m.setupFields() {
		if field.input == nil {
			continue
		}
		if field.step == stepAge {
			field.input.Width = min(10, fieldWidth)
			continue
		}
		field.input.Width = fieldWidth
	}
}

func (m setupModel) Init() tea.Cmd {
	return textinput.Blink
}

func (m setupModel) footer() []string {
	if m.step == stepLanding {
		if m.canCancel {
			return []string{"Enter Start", "Esc Dashboard", "Ctrl+C Quit"}
		}
		return []string{"Enter Start", "Ctrl+C Quit"}
	}
	field, ok := m.currentField()
	if m.editing && m.step == stepAge {
		return []string{"Enter Continue", "Esc Settings", "Ctrl+C Quit"}
	}
	if ok && field.kind == setupConfirm {
		return []string{"Enter Submit", "Esc Back", "Ctrl+C Quit"}
	}
	if ok && field.kind == setupMultiLine {
		actions := []string{"Enter Add Item", "Enter(empty) Next"}
		if len(*field.lines) > 0 {
			actions = append(actions, "Up/Down Select", "Delete Remove")
		}
		return append(actions, "Esc Back", "Ctrl+C Quit")
	}
	return setupFooter
}

func (m *setupModel) setupFields() []setupField {
	return []setupField{
		{step: stepAge, label: "Age", prompt: "Enter your age", input: &m.age, kind: setupSingleLine},
		{step: stepGender, label: "Gender", prompt: "Enter your gender identity", input: &m.gender, kind: setupSingleLine},
		{step: stepPMH, label: "Past Medical History", prompt: "Enter past conditions one at a time · Empty Enter to finish", input: &m.pmh, lines: &m.pmhLines, kind: setupMultiLine},
		{step: stepMedications, label: "Current Medications", prompt: "Enter current medications one at a time · Empty Enter to finish", input: &m.medications, lines: &m.medicationsLines, kind: setupMultiLine},
		{step: stepAllergies, label: "Allergies", prompt: "Enter allergies one at a time · Empty Enter to finish", input: &m.allergies, lines: &m.allergiesLines, kind: setupMultiLine},
		{step: stepFamilyHistory, label: "Family History", prompt: "Enter family conditions one at a time · Empty Enter to finish", input: &m.familyHist, lines: &m.familyHistLines, kind: setupMultiLine},
		{step: stepSmoking, label: "Smoking Status", prompt: "Describe your smoking history", input: &m.smoking, kind: setupSingleLine},
		{step: stepAlcohol, label: "Alcohol Use", prompt: "Describe your alcohol consumption", input: &m.alcohol, kind: setupSingleLine},
		{step: stepExercise, label: "Exercise / Physical Activity", prompt: "Describe your physical activity level", input: &m.exercise, kind: setupSingleLine},
		{step: stepConfirm, label: "Review & Submit", prompt: "Press Enter to submit your profile", kind: setupConfirm},
	}
}

func (m *setupModel) currentField() (setupField, bool) {
	for _, field := range m.setupFields() {
		if field.step == m.step {
			return field, true
		}
	}
	return setupField{}, false
}

func (m *setupModel) focusCurrentField() {
	if field, ok := m.currentField(); ok && field.input != nil {
		field.input.Focus()
	}
}

type profileSubmittedMsg struct {
	err error
}

func submitProfile(userid string, m setupModel) tea.Cmd {
	return func() tea.Msg {
		if m.worker == nil {
			return profileSubmittedMsg{}
		}
		body := m.profileUpdateBody(userid)

		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		_, err := m.worker.Call(ctx, "profile/update", body)
		if err != nil {
			return profileSubmittedMsg{err: err}
		}

		return profileSubmittedMsg{}
	}
}

func (m setupModel) profileUpdateBody(userid string) map[string]interface{} {
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
	if m.medicalSummary != "" {
		body["medical_summary"] = m.medicalSummary
	}
	return body
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

		if m.step == stepLanding {
			switch key {
			case "ctrl+c":
				return m, tea.Quit
			case "esc":
				if m.canCancel {
					m.cancelled = true
				}
				return m, nil
			case "enter":
				m.step = stepAge
				m.focusCurrentField()
				return m, textinput.Blink
			}
			return m, nil
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
	if field, ok := m.currentField(); ok && field.kind == setupSingleLine {
		*field.input, cmd = field.input.Update(msg)
	}
	return m, cmd
}

func (m *setupModel) isMultiLineStep() bool {
	field, ok := m.currentField()
	return ok && field.kind == setupMultiLine
}

func (m *setupModel) updateMultiLineStep(msg tea.KeyMsg) (setupModel, tea.Cmd) {
	key := msg.String()
	field, ok := m.currentField()
	if !ok || field.input == nil || field.lines == nil {
		return *m, nil
	}

	if key == "esc" {
		// Clear current input and go back.
		field.input.SetValue("")
		return m.goBack()
	}
	if key == "up" || key == "down" {
		if len(*field.lines) > 0 {
			delta := 1
			if key == "up" {
				delta = -1
			}
			m.listCursor = (m.listCursor + delta + len(*field.lines)) % len(*field.lines)
		}
		return *m, nil
	}
	if key == "delete" {
		if len(*field.lines) > 0 {
			m.listCursor = min(m.listCursor, len(*field.lines)-1)
			*field.lines = slices.Delete(*field.lines, m.listCursor, m.listCursor+1)
			if len(*field.lines) == 0 {
				m.listCursor = 0
			} else {
				m.listCursor = min(m.listCursor, len(*field.lines)-1)
			}
		}
		return *m, nil
	}

	if key == "enter" {
		value := strings.TrimSpace(field.input.Value())
		if value == "" {
			// Empty input = finish this step, advance.
			field.input.SetValue("")
			return m.advanceStep()
		}
		// Append to list and clear input.
		*field.lines = append(*field.lines, value)
		m.listCursor = len(*field.lines) - 1
		field.input.SetValue("")
		return *m, nil
	}

	// Forward typing to textinput.
	var cmd tea.Cmd
	*field.input, cmd = field.input.Update(msg)
	return *m, cmd
}

func (m setupModel) advanceStep() (setupModel, tea.Cmd) {
	m.err = nil
	if m.step == stepConfirm {
		m.submitting = true
		return m, submitProfile(m.userid, m)
	}

	next := m.step + 1
	if next > stepConfirm {
		return m, nil
	}
	m.step = next
	m.listCursor = 0

	// Focus the appropriate input for the new step.
	m.focusCurrentField()
	return m, textinput.Blink
}

func (m setupModel) goBack() (setupModel, tea.Cmd) {
	if m.editing && m.step == stepAge {
		m.cancelled = true
		return m, nil
	}
	if m.step == stepLanding {
		if m.canCancel {
			m.cancelled = true
		}
		return m, nil
	}
	prev := m.step - 1
	if prev < stepLanding {
		prev = stepLanding
	}
	m.step = prev
	m.listCursor = 0

	if m.step != stepLanding {
		m.focusCurrentField()
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

func (m setupModel) renderAnchored(content string) string {
	paneWidth := m.width - 8
	if paneWidth < 30 {
		paneWidth = m.width
	}
	if paneWidth > 72 {
		paneWidth = 72
	}

	body := lipgloss.NewStyle().
		Width(paneWidth).
		Align(lipgloss.Left).
		Render(content)

	topPad := m.height / 5
	if topPad < 1 {
		topPad = 0
	}

	return lipgloss.Place(
		m.width, m.height,
		lipgloss.Center, lipgloss.Top,
		strings.Repeat("\n", topPad)+body,
	)
}

func (m setupModel) renderLanding() string {
	subtitle := systemStyle.Render("Your AI-powered clinical assistant")

	boxStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(colorPrimary).
		Padding(2, 4).
		Margin(1, 0)

	features := []string{
		"[1] Intelligent patient intake",
		"[2] Evidence-based research",
		"[3] Differential diagnosis support",
		"[4] Client-side encrypted storage",
	}

	featureList := lipgloss.JoinVertical(lipgloss.Left, features...)
	box := boxStyle.Render(featureList)

	content := lipgloss.JoinVertical(
		lipgloss.Center,
		subtitle,
		"",
		box,
		"",
		hintStyle.Render("Press Enter to set up your profile."),
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

	return m.renderAnchored(content)
}

func (m setupModel) renderField() string {
	labelStyle := lipgloss.NewStyle().Bold(true).Foreground(colorPrimary)
	field, ok := m.currentField()
	if !ok {
		return ""
	}

	if field.kind == setupConfirm {
		return m.renderSummary()
	}
	if field.kind == setupMultiLine {
		return m.renderMultiLineField(field.label, *field.lines, field.input.View())
	}
	return lipgloss.JoinVertical(lipgloss.Left,
		labelStyle.Render(field.label),
		field.input.View(),
	)
}

func (m setupModel) renderMultiLineField(title string, lines []string, inputView string) string {
	labelStyle := lipgloss.NewStyle().Bold(true).Foreground(colorPrimary)
	itemStyle := lipgloss.NewStyle().Foreground(colorAccent).PaddingLeft(4)

	var sb strings.Builder
	sb.WriteString(labelStyle.Render(title))
	sb.WriteString("\n")
	sb.WriteString("\n")

	if len(lines) > 0 {
		for i, line := range lines {
			marker := "• "
			style := itemStyle
			if i == min(m.listCursor, len(lines)-1) {
				marker = "> "
				style = style.Bold(true).Foreground(colorPrimary)
			}
			sb.WriteString(style.Render(marker + line))
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

	sections := []struct {
		title string
		lines []string
	}{
		{title: "Past Medical History", lines: m.pmhLines},
		{title: "Medications", lines: m.medicationsLines},
		{title: "Allergies", lines: m.allergiesLines},
		{title: "Family History", lines: m.familyHistLines},
	}
	for _, section := range sections {
		sb.WriteString(systemStyle.Render(section.title))
		sb.WriteString("\n")
		for _, s := range section.lines {
			sb.WriteString(itemStyle.Render("• " + s))
			sb.WriteString("\n")
		}
		sb.WriteString("\n")
	}

	sb.WriteString(systemStyle.Render("Social History"))
	sb.WriteString("\n")
	for i, item := range []string{
		fmt.Sprintf("Smoking: %s", m.smoking.Value()),
		fmt.Sprintf("Alcohol: %s", m.alcohol.Value()),
		fmt.Sprintf("Exercise: %s", m.exercise.Value()),
	} {
		sb.WriteString(itemStyle.Render(item))
		if i < 2 {
			sb.WriteString("\n")
		}
	}

	return sb.String()
}

func (m setupModel) renderSubmitting() string {
	content := lipgloss.JoinVertical(
		lipgloss.Center,
		systemStyle.Render("Please wait while we set up your account."),
	)
	return m.renderAnchored(content)
}

func (m setupModel) renderDone() string {
	content := lipgloss.JoinVertical(
		lipgloss.Center,
		systemStyle.Render("Your account is ready."),
		"",
		hintStyle.Render("Opening chat..."),
	)
	return m.renderAnchored(content)
}

func (m setupModel) stepLabel() string {
	if field, ok := m.currentField(); ok {
		if field.step == stepSmoking {
			return "Smoking History"
		}
		if field.step == stepExercise {
			return "Physical Activity"
		}
		return field.label
	}
	return ""
}

func (m setupModel) stepNumber() int {
	return int(m.step)
}

func (m setupModel) stepPrompt() string {
	if field, ok := m.currentField(); ok {
		return field.prompt
	}
	return ""
}
