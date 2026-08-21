/**
 * App Page Object — main authenticated app shell.
 * Encapsulates sidebar navigation and modal opening.
 */
import { Page, Locator } from '@playwright/test'

export class AppPage {
  readonly page: Page

  // Sidebar navigation
  readonly sidebar: Locator
  readonly sidebarToggle: Locator
  readonly composeButton: Locator
  readonly navInbox: Locator
  readonly navDrafts: Locator
  readonly navSent: Locator
  readonly navArchived: Locator
  readonly navSpam: Locator
  readonly navTrash: Locator
  readonly navSettings: Locator
  readonly navSupport: Locator

  // Main content
  readonly appContainer: Locator
  readonly appMain: Locator

  constructor(page: Page) {
    this.page = page
    this.sidebar = page.getByTestId('sidebar')
    this.sidebarToggle = page.getByTestId('sidebar-toggle')
    this.composeButton = page.getByTestId('compose-button')
    this.navInbox = page.getByTestId('nav-inbox')
    this.navDrafts = page.getByTestId('nav-drafts')
    this.navSent = page.getByTestId('nav-sent')
    this.navArchived = page.getByTestId('nav-archived')
    this.navSpam = page.getByTestId('nav-spam')
    this.navTrash = page.getByTestId('nav-trash')
    this.navSettings = page.getByTestId('nav-settings')
    this.navSupport = page.getByTestId('nav-support')
    this.appContainer = page.getByTestId('app-container')
    this.appMain = page.getByTestId('app-main')
  }

  async goto() {
    await this.page.goto('/')
  }

  async waitForReady() {
    await this.navInbox.waitFor({ state: 'visible', timeout: 15000 })
  }

  async navigateToInbox() {
    await this.navInbox.click()
  }

  async navigateToDrafts() {
    await this.navDrafts.click()
  }

  async navigateToSent() {
    await this.navSent.click()
  }

  async navigateToArchived() {
    await this.navArchived.click()
  }

  async navigateToSpam() {
    await this.navSpam.click()
  }

  async navigateToTrash() {
    await this.navTrash.click()
  }

  async openSettings() {
    await this.navSettings.click()
  }

  async openSettingsWithShortcut() {
    await this.page.keyboard.press('Meta+,')
  }

  async openCompose() {
    await this.composeButton.click()
  }

  async openCommandPalette() {
    await this.page.keyboard.press('Meta+k')
  }

  async openShortcutsHelp() {
    await this.page.keyboard.press('Meta+/')
  }

  async toggleSidebar() {
    await this.sidebarToggle.click()
  }
}
