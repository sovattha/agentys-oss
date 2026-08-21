import React from 'react';
import { render } from '@testing-library/react-native';
import { DrivePlayer } from '../../src/components/DrivePlayer';

const defaultProps = {
  onNext: jest.fn(),
};

const DRAFT_CONTENT = 'Bonjour, je confirme la réunion pour demain.';

describe('DrivePlayer', () => {
  beforeEach(() => jest.clearAllMocks());

  describe('state idle', () => {
    it("masque le statut tant qu'aucune session n'est active", () => {
      const { queryByText } = render(
        <DrivePlayer {...defaultProps} state="idle" />
      );
      expect(queryByText('PRÊT')).toBeNull();
      expect(queryByText('CHARGEMENT')).toBeNull();
    });
  });

  describe('state loading', () => {
    it("affiche 'Chargement'", () => {
      const { getByText } = render(<DrivePlayer {...defaultProps} state="loading" />);
      expect(getByText('Chargement')).toBeTruthy();
    });
  });

  describe('state speaking', () => {
    it("affiche 'Lecture', infos sender/subject", () => {
      const { getByText } = render(
        <DrivePlayer
          {...defaultProps}
          state="speaking"
          senderName="Marie Dupont"
          emailSubject="Rapport Q4"
        />
      );
      expect(getByText('Lecture')).toBeTruthy();
      expect(getByText('Marie Dupont')).toBeTruthy();
      expect(getByText('Rapport Q4')).toBeTruthy();
    });
  });

  describe('state choosing', () => {
    it("affiche 'Que faire ?' SANS chips de mots d'action (retirés 2026-07)", () => {
      const { getByText, queryByText } = render(
        <DrivePlayer {...defaultProps} state="choosing" />
      );
      expect(getByText('Que faire ?')).toBeTruthy();
      // Interaction 100% voix + gestes : les chips ne doivent plus rendre.
      expect(queryByText('répondre')).toBeNull();
      expect(queryByText('transférer')).toBeNull();
      expect(queryByText('suivant')).toBeNull();
      expect(queryByText('précédent')).toBeNull();
    });
  });

  describe('state listening', () => {
    it("affiche 'Dictée'", () => {
      const { getByText } = render(
        <DrivePlayer {...defaultProps} state="listening" />
      );
      expect(getByText('Dictée')).toBeTruthy();
    });
  });

  describe('state generating', () => {
    it("affiche 'Génération'", () => {
      const { getByText } = render(<DrivePlayer {...defaultProps} state="generating" />);
      expect(getByText('Génération')).toBeTruthy();
    });
  });

  describe('state reviewing', () => {
    it("affiche 'Brouillon' SANS chips (voix + gestes uniquement)", () => {
      const { getByText, queryByText } = render(
        <DrivePlayer {...defaultProps} state="reviewing" draftContent={DRAFT_CONTENT} />
      );
      expect(getByText('Brouillon')).toBeTruthy();
      expect(queryByText('approuver')).toBeNull();
      expect(queryByText('refaire')).toBeNull();
      expect(queryByText('suivant')).toBeNull();
    });
  });
});
