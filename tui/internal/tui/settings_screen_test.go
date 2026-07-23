package tui

import (
	"errors"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

const settingsTestUserID = "ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9"

func readySettingsModel() settingsModel {
	m := newSettingsModel(settingsTestUserID, "alice", nil)
	m.loading = false
	m.SetSize(80, 20)
	m.data = settingsData{
		Profile: profileSettings{
			Demographics: map[string]string{"age": "35", "gender": "Female"},
			Allergies:    []string{"penicillin"},
			Social:       map[string]string{"exercise": "Daily walking"},
		},
		ProviderSetup: providerSetupInput{
			LLMProvider:    "OpenRouter",
			LLMAPIKey:      "sk-secret",
			LLMBaseURL:     "https://openrouter.ai/api/v1",
			SearchProvider: "Exa",
			SearchAPIKey:   "exa-secret",
		},
	}
	return m
}

func TestSettingsNavigationAndActions(t *testing.T) {
	m := readySettingsModel()
	m, _ = m.Update(testKey("down"))
	if settingsCategory(m.categoryCursor) != settingsProfile {
		t.Fatalf("down selected %v, want profile", settingsCategory(m.categoryCursor))
	}
	m, _ = m.Update(testKey("enter"))
	if m.focus != settingsContentFocus {
		t.Fatal("enter on sidebar should focus content")
	}
	m, _ = m.Update(testKey("enter"))
	if m.action != settingsActionEditProfile {
		t.Fatalf("profile action = %v", m.action)
	}

	m.action = settingsActionNone
	m, _ = m.Update(testKey("left"))
	m, _ = m.Update(testKey("down"))
	if settingsCategory(m.categoryCursor) != settingsProviders {
		t.Fatalf("down selected %v, want providers", settingsCategory(m.categoryCursor))
	}
	m, _ = m.Update(testKey("right"))
	m, _ = m.Update(testKey("enter"))
	if m.action != settingsActionEditProviders {
		t.Fatalf("provider action = %v", m.action)
	}

	m, _ = m.Update(testKey("esc"))
	if !m.close {
		t.Fatal("esc should close settings")
	}
}

func TestSettingsViewShowsRealValuesButNeverSecrets(t *testing.T) {
	m := readySettingsModel()
	m.categoryCursor = int(settingsProviders)
	view := m.View()
	for _, expected := range []string{"Account", "Medical Profile", "Providers", "Data", "OpenRouter", "Exa", "Edit providers"} {
		if !strings.Contains(view, expected) {
			t.Fatalf("settings view missing %q", expected)
		}
	}
	for _, secret := range []string{"sk-secret", "exa-secret"} {
		if strings.Contains(view, secret) {
			t.Fatalf("settings view exposed provider secret %q", secret)
		}
	}
}

func TestSettingsResponsiveLayout(t *testing.T) {
	m := readySettingsModel()
	for _, size := range []struct{ width, height int }{{80, 20}, {120, 36}} {
		m.SetSize(size.width, size.height)
		view := m.View()
		if got := lipgloss.Width(view); got > size.width {
			t.Fatalf("view width %d exceeds terminal width %d", got, size.width)
		}
		if got := lipgloss.Height(view); got > size.height {
			t.Fatalf("view height %d exceeds body height %d", got, size.height)
		}
	}

	m.SetSize(settingsMinWidth-1, settingsMinHeight)
	if view := m.View(); !strings.Contains(view, "Terminal too small") {
		t.Fatalf("narrow view should show resize message: %q", view)
	}
}

func TestSettingsFitsInsideApplicationChrome(t *testing.T) {
	m := newModel(settingsTestUserID, true, true, true, nil)
	m.active = settingsScreen
	updated, _ := m.Update(tea.WindowSizeMsg{Width: 80, Height: 24})
	m = updated.(model)
	updated, _ = m.Update(settingsLoadedMsg{data: readySettingsModel().data})
	m = updated.(model)

	view := m.View()
	if got := lipgloss.Width(view); got > 80 {
		t.Fatalf("application width %d exceeds terminal width", got)
	}
	if got := lipgloss.Height(view); got > 24 {
		t.Fatalf("application height %d exceeds terminal height", got)
	}
}

func TestSettingsLoadFailureCanRetry(t *testing.T) {
	m := readySettingsModel()
	m.loadErr = "temporary failure"
	m, cmd := m.Update(testKey("r"))
	if !m.loading || m.loadErr != "" || cmd == nil {
		t.Fatal("r should clear the error and retry settings loading")
	}
}

func TestSettingsBackupStateAndDuplicatePrevention(t *testing.T) {
	m := readySettingsModel()
	m.categoryCursor = int(settingsDataCategory)
	m.focus = settingsContentFocus

	m, cmd := m.Update(testKey("enter"))
	if !m.backingUp || cmd == nil {
		t.Fatal("Back Up Now should start an asynchronous backup")
	}
	_, duplicate := m.Update(testKey("enter"))
	if duplicate != nil {
		t.Fatal("a running backup must ignore duplicate submissions")
	}

	msg := cmd()
	m, _ = m.Update(msg)
	if m.backingUp || !strings.Contains(m.backupErr, "unavailable") {
		t.Fatalf("backup failure state = backingUp:%v error:%q", m.backingUp, m.backupErr)
	}

	m.backingUp = true
	m, _ = m.Update(settingsBackupMsg{})
	if m.backingUp || m.backupStatus == "" {
		t.Fatal("successful backup should display completion status")
	}
}

func TestSettingsRestoreListConfirmationAndSuccess(t *testing.T) {
	m := readySettingsModel()
	m.categoryCursor = int(settingsDataCategory)
	m.focus = settingsContentFocus
	m.dataCursor = 1

	m, cmd := m.Update(testKey("enter"))
	if m.dataView != settingsDataRestoreList || !m.loadingBackups || cmd == nil {
		t.Fatal("Restore from Backup should load backups asynchronously")
	}

	m, _ = m.Update(settingsBackupsMsg{backups: []backupMetadata{
		{ID: "backup-new", Checksum: strings.Repeat("a", 64), CreatedAt: "2026-07-23T12:30:00Z"},
		{ID: "backup-old", Checksum: strings.Repeat("b", 64), CreatedAt: "2026-07-22T12:30:00Z"},
	}})
	if m.loadingBackups || !strings.Contains(m.View(), "backup-") {
		t.Fatal("loaded backups should be visible")
	}
	m, _ = m.Update(testKey("down"))
	if m.backupCursor != 1 {
		t.Fatal("down should select the next backup")
	}
	m, _ = m.Update(testKey("enter"))
	if m.dataView != settingsDataRestoreConfirm {
		t.Fatal("selecting a backup should open confirmation")
	}

	m.confirmInput.SetValue("wrong")
	m, cmd = m.Update(testKey("enter"))
	if cmd != nil || m.restoring || !strings.Contains(m.restoreErr, "RESTORE") {
		t.Fatal("restore must require the exact confirmation text")
	}

	m.confirmInput.SetValue("RESTORE")
	m, cmd = m.Update(testKey("enter"))
	if !m.restoring || cmd == nil {
		t.Fatal("valid confirmation should start restore asynchronously")
	}
	m, cmd = m.Update(settingsRestoreMsg{})
	if m.restoring || m.restoreStatus == "" || cmd == nil {
		t.Fatal("successful restore should show status and schedule a clean exit")
	}
}

func TestSettingsRestoreBackNavigationAndErrors(t *testing.T) {
	m := readySettingsModel()
	m.categoryCursor = int(settingsDataCategory)
	m.focus = settingsContentFocus
	m.dataView = settingsDataRestoreList
	m.listErr = "temporary failure"

	m, cmd := m.Update(testKey("r"))
	if !m.loadingBackups || m.listErr != "" || cmd == nil {
		t.Fatal("r should retry a failed backup listing")
	}
	m, _ = m.Update(testKey("esc"))
	if m.dataView != settingsDataActions || m.close {
		t.Fatal("Esc from backup list should return to Data actions")
	}
	m, _ = m.Update(settingsBackupsMsg{err: errors.New("late response")})
	if m.authRequired || m.listErr != "" {
		t.Fatal("a completed list request should be ignored after leaving the list")
	}

	m.dataView = settingsDataRestoreList
	m.backups = []backupMetadata{{ID: "backup-one", Checksum: strings.Repeat("a", 64)}}
	m, _ = m.Update(testKey("enter"))
	m, _ = m.Update(testKey("esc"))
	if m.dataView != settingsDataRestoreList || m.close {
		t.Fatal("Esc from confirmation should return to the backup list")
	}
}

func TestBackupLabelUsesLocalTimeAndShortID(t *testing.T) {
	label := backupLabel(backupMetadata{
		ID:        "12345678-aaaa-bbbb",
		CreatedAt: "2026-07-23T12:30:00Z",
	})
	if !strings.Contains(label, "2026-07-23") || !strings.Contains(label, "12345678") {
		t.Fatalf("backup label missing timestamp or short ID: %q", label)
	}
}

func TestSettingsEditorsPrefillAndCancel(t *testing.T) {
	settings := readySettingsModel()
	profile := newProfileEditor(settingsTestUserID, nil, settings.data.Profile)
	if profile.age.Value() != "35" || profile.gender.Value() != "Female" || profile.allergiesLines[0] != "penicillin" {
		t.Fatal("profile editor was not prefilled")
	}
	profile, _ = profile.Update(testKey("esc"))
	if !profile.cancelled {
		t.Fatal("esc on the first profile field should return to settings")
	}

	providers := newProviderEditor(settingsTestUserID, nil, settings.data.ProviderSetup)
	if providers.llmProvider != "OpenRouter" || providers.searchProvider != "Exa" || providers.llmAPIKey.Value() != "sk-secret" {
		t.Fatal("provider editor was not prefilled")
	}
	providers, _ = providers.Update(testKey("esc"))
	if !providers.cancelled {
		t.Fatal("esc on the first provider step should return to settings")
	}
}

func TestProviderEditorDoesNotReuseKeyForDifferentProvider(t *testing.T) {
	settings := readySettingsModel()
	m := newProviderEditor(settingsTestUserID, nil, settings.data.ProviderSetup)
	m = m.moveCursor(1)
	m, _ = m.Update(testKey("enter"))

	if m.llmProvider == "OpenRouter" {
		t.Fatal("test did not select a different provider")
	}
	if m.llmAPIKey.Value() != "" || m.llmBaseURL.Value() != "" {
		t.Fatal("changing providers must clear the previous provider's credentials")
	}
}

func TestSettingsEditorAndReauthenticationReturnPaths(t *testing.T) {
	m := newModel(settingsTestUserID, true, true, true, nil)
	m.active = settingsScreen
	m.settings = readySettingsModel()
	m.settings.categoryCursor = int(settingsProfile)
	m.settings.focus = settingsContentFocus

	updated, _ := m.Update(testKey("enter"))
	m = updated.(model)
	if m.active != setupScreen || !m.returnToSettings {
		t.Fatalf("profile edit did not open setup: active=%v return=%v", m.active, m.returnToSettings)
	}
	updated, _ = m.Update(testKey("esc"))
	m = updated.(model)
	if m.active != settingsScreen || settingsCategory(m.settings.categoryCursor) != settingsProfile {
		t.Fatalf("cancel did not return to profile settings: active=%v category=%v", m.active, settingsCategory(m.settings.categoryCursor))
	}

	m.backendUsername = "alice"
	m.settings.categoryCursor = int(settingsDataCategory)
	updated, _ = m.updateSettings(settingsBackupMsg{err: errors.New("expired"), authRequired: true})
	m = updated.(model)
	if m.active != backendAccountScreen || !m.reauthPending || m.reauthReturn != settingsScreen {
		t.Fatal("backup authentication failure should open sign-in and preserve settings return")
	}
	updated, _ = m.updateBackendAccount(backendAccountSubmittedMsg{})
	m = updated.(model)
	if m.active != settingsScreen || m.reauthPending {
		t.Fatal("successful sign-in should return to settings")
	}
}
