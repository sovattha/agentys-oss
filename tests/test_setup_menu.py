import re
from io import StringIO
from unittest.mock import patch



def extract_menu_lines(output: str) -> list[str]:
    """Extract numbered menu lines from output, removing ANSI codes."""
    lines = output.strip().split('\n')
    menu_lines = []
    for line in lines:
        clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
        if re.match(r'\s*\d+\.\s+', clean):
            menu_lines.append(clean.strip())
    return menu_lines


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


class TestMainMenuOrder:
    def test_imap_smtp_appears_before_gmail_with_recommended_label(self):
        from setup import main_menu

        with patch('builtins.input', side_effect=['0']):
            with patch('sys.stdout', new=StringIO()) as mock_stdout:
                main_menu()
                output = mock_stdout.getvalue()

        menu_lines = extract_menu_lines(output)

        imap_line = next((line for line in menu_lines if 'IMAP' in line), None)
        gmail_line = next((line for line in menu_lines if 'Gmail' in line), None)

        assert imap_line is not None, "IMAP/SMTP option not found in menu"
        assert gmail_line is not None, "Gmail option not found in menu"

        imap_index = menu_lines.index(imap_line)
        gmail_index = menu_lines.index(gmail_line)

        assert imap_index < gmail_index, f"IMAP/SMTP should appear before Gmail. IMAP at {imap_index}, Gmail at {gmail_index}"
        assert 'recommandé' in imap_line.lower(), "IMAP/SMTP option should have '(recommandé)' label"

    def test_option_2_is_imap_smtp(self):
        from setup import main_menu

        with patch('builtins.input', side_effect=['0']):
            with patch('sys.stdout', new=StringIO()) as mock_stdout:
                main_menu()
                output = mock_stdout.getvalue()

        menu_lines = extract_menu_lines(output)
        option_2 = next((line for line in menu_lines if line.startswith('2.')), None)

        assert option_2 is not None, "Option 2 not found"
        assert 'IMAP' in option_2, f"Option 2 should be IMAP/SMTP, got: {option_2}"

    def test_option_3_is_gmail(self):
        from setup import main_menu

        with patch('builtins.input', side_effect=['0']):
            with patch('sys.stdout', new=StringIO()) as mock_stdout:
                main_menu()
                output = mock_stdout.getvalue()

        menu_lines = extract_menu_lines(output)
        option_3 = next((line for line in menu_lines if line.startswith('3.')), None)

        assert option_3 is not None, "Option 3 not found"
        assert 'Gmail' in option_3, f"Option 3 should be Gmail, got: {option_3}"


class TestMenuChoiceRouting:
    """Tests that menu choices route to correct functions."""

    def test_choice_2_calls_setup_imap_smtp(self):
        """Option 2 should call setup_imap_smtp function."""
        from setup import main_menu

        with patch('setup.setup_imap_smtp') as mock_imap:
            with patch('setup.press_enter'):
                with patch('builtins.input', side_effect=['2', '0']):
                    with patch('sys.stdout', new=StringIO()):
                        main_menu()

        mock_imap.assert_called_once()

    def test_choice_3_calls_setup_gmail(self):
        """Option 3 should call setup_gmail function."""
        from setup import main_menu

        with patch('setup.setup_gmail') as mock_gmail:
            with patch('setup.press_enter'):
                with patch('builtins.input', side_effect=['3', '0']):
                    with patch('sys.stdout', new=StringIO()):
                        main_menu()

        mock_gmail.assert_called_once()

    def test_choice_1_calls_setup_llm(self):
        """Option 1 should call setup_llm function."""
        from setup import main_menu

        with patch('setup.setup_llm') as mock_llm:
            with patch('setup.press_enter'):
                with patch('builtins.input', side_effect=['1', '0']):
                    with patch('sys.stdout', new=StringIO()):
                        main_menu()

        mock_llm.assert_called_once()


class TestMenuEdgeCases:
    """Tests for edge cases in menu handling."""

    def test_choice_0_exits_menu(self):
        """Option 0 should exit the menu."""
        from setup import main_menu

        with patch('builtins.input', side_effect=['0']):
            with patch('sys.stdout', new=StringIO()) as mock_stdout:
                main_menu()
                output = strip_ansi(mock_stdout.getvalue())

        assert 'À bientôt' in output

    def test_empty_input_continues_menu(self):
        """Empty input should continue to next iteration."""
        from setup import main_menu

        with patch('builtins.input', side_effect=['', '0']):
            with patch('sys.stdout', new=StringIO()) as mock_stdout:
                main_menu()
                output = strip_ansi(mock_stdout.getvalue())

        assert 'À bientôt' in output

    def test_invalid_choice_shows_error(self):
        """Invalid choice should display error message."""
        from setup import main_menu

        with patch('builtins.input', side_effect=['x', '0']):
            with patch('sys.stdout', new=StringIO()) as mock_stdout:
                main_menu()
                output = strip_ansi(mock_stdout.getvalue())

        assert 'invalide' in output.lower()

    def test_whitespace_input_continues_menu(self):
        """Whitespace-only input should continue to next iteration."""
        from setup import main_menu

        with patch('builtins.input', side_effect=['   ', '0']):
            with patch('sys.stdout', new=StringIO()) as mock_stdout:
                main_menu()
                output = strip_ansi(mock_stdout.getvalue())

        assert 'À bientôt' in output

    def test_uppercase_input_is_normalized(self):
        """Uppercase input should be normalized to lowercase."""
        from setup import main_menu

        with patch('setup.reset_config') as mock_reset:
            with patch('setup.press_enter'):
                with patch('builtins.input', side_effect=['R', '0']):
                    with patch('sys.stdout', new=StringIO()):
                        main_menu()

        mock_reset.assert_called_once()


class TestMenuEmailNotConfigured:
    """Tests for menu behavior when email is not configured."""

    def test_option_7_shows_warning_when_email_not_configured(self):
        """Option 7 should warn when email is not configured."""
        from setup import main_menu

        with patch('setup.get_current_provider', return_value=None):
            with patch('setup.is_provider_ready', return_value=False):
                with patch('setup.press_enter'):
                    with patch('builtins.input', side_effect=['7', '0']):
                        with patch('sys.stdout', new=StringIO()) as mock_stdout:
                            main_menu()
                            output = strip_ansi(mock_stdout.getvalue())

        assert 'Configure' in output or 'provider email' in output.lower()

    def test_option_8_shows_warning_when_email_not_configured(self):
        """Option 8 should warn when email is not configured."""
        from setup import main_menu

        with patch('setup.get_current_provider', return_value=None):
            with patch('setup.is_provider_ready', return_value=False):
                with patch('setup.press_enter'):
                    with patch('builtins.input', side_effect=['8', '0']):
                        with patch('sys.stdout', new=StringIO()) as mock_stdout:
                            main_menu()
                            output = strip_ansi(mock_stdout.getvalue())

        assert 'Configure' in output or 'provider email' in output.lower()

    def test_option_d_shows_warning_when_email_not_configured(self):
        """Option 'd' (daemon) should warn when email is not configured."""
        from setup import main_menu

        with patch('setup.get_current_provider', return_value=None):
            with patch('setup.is_provider_ready', return_value=False):
                with patch('setup.press_enter'):
                    with patch('builtins.input', side_effect=['d', '0']):
                        with patch('sys.stdout', new=StringIO()) as mock_stdout:
                            main_menu()
                            output = strip_ansi(mock_stdout.getvalue())

        assert 'Configure' in output or 'provider email' in output.lower()


class TestMenuEmailConfigured:
    """Tests for menu behavior when email is configured."""

    def test_option_7_calls_test_provider_when_configured(self):
        """Option 7 should call test_provider when email is configured."""
        from setup import main_menu

        with patch('setup.get_current_provider', return_value='imap'):
            with patch('setup.is_provider_ready', return_value=True):
                with patch('setup.test_provider') as mock_test:
                    with patch('setup.press_enter'):
                        with patch('builtins.input', side_effect=['7', '0']):
                            with patch('sys.stdout', new=StringIO()):
                                main_menu()

        mock_test.assert_called_once()

    def test_option_d_shows_daemon_instructions_when_configured(self):
        """Option 'd' should show daemon instructions when email is configured."""
        from setup import main_menu

        with patch('setup.get_current_provider', return_value='imap'):
            with patch('setup.is_provider_ready', return_value=True):
                with patch('setup.press_enter'):
                    with patch('builtins.input', side_effect=['d', '0']):
                        with patch('sys.stdout', new=StringIO()) as mock_stdout:
                            main_menu()
                            output = strip_ansi(mock_stdout.getvalue())

        assert 'run_daemon.py' in output


class TestMainFunction:
    """Tests for the main() entry point."""

    def test_main_with_status_flag(self):
        """main() with --status should call show_status."""
        import sys
        from setup import main

        with patch.object(sys, 'argv', ['setup.py', '--status']):
            with patch('setup.show_status') as mock_status:
                with patch('sys.stdout', new=StringIO()):
                    main()

        mock_status.assert_called_once()

    def test_main_with_test_flag(self):
        """main() with --test should call test_provider."""
        import sys
        from setup import main

        with patch.object(sys, 'argv', ['setup.py', '--test']):
            with patch('setup.test_provider') as mock_test:
                with patch('sys.stdout', new=StringIO()):
                    main()

        mock_test.assert_called_once()

    def test_main_with_invalid_flag_shows_usage(self):
        """main() with invalid flag should show usage."""
        import sys
        from setup import main

        with patch.object(sys, 'argv', ['setup.py', '--invalid']):
            with patch('sys.stdout', new=StringIO()) as mock_stdout:
                main()
                output = mock_stdout.getvalue()

        assert 'Usage' in output

    def test_main_without_args_calls_main_menu(self):
        """main() without args should call main_menu."""
        import sys
        from setup import main

        with patch.object(sys, 'argv', ['setup.py']):
            with patch('setup.main_menu') as mock_menu:
                main()

        mock_menu.assert_called_once()


class TestProviderDisplayOrder:
    """Tests for provider display order in show_status."""

    def test_imap_smtp_displayed_before_gmail_outlook_in_providers_section(self):
        """IMAP/SMTP should be displayed before Gmail/Outlook in providers section."""
        from setup import show_status

        with patch('setup.get_current_provider', return_value=None):
            with patch('sys.stdout', new=StringIO()) as mock_stdout:
                with patch('setup.clear'):
                    show_status()
                    output = strip_ansi(mock_stdout.getvalue())

        providers_section_start = output.find('Providers disponibles')
        assert providers_section_start != -1, "Providers section not found"

        providers_section = output[providers_section_start:]

        imap_pos = providers_section.find('IMAP')
        smtp_pos = providers_section.find('SMTP')
        gmail_pos = providers_section.find('GMAIL')
        outlook_pos = providers_section.find('OUTLOOK')

        assert imap_pos != -1, "IMAP not found in providers section"
        assert smtp_pos != -1, "SMTP not found in providers section"
        assert gmail_pos != -1, "GMAIL not found in providers section"
        assert outlook_pos != -1, "OUTLOOK not found in providers section"

        assert imap_pos < gmail_pos, "IMAP should appear before GMAIL in providers list"
        assert imap_pos < outlook_pos, "IMAP should appear before OUTLOOK in providers list"
        assert smtp_pos < gmail_pos, "SMTP should appear before GMAIL in providers list"
        assert smtp_pos < outlook_pos, "SMTP should appear before OUTLOOK in providers list"
