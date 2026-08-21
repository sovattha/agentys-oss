// Compatibility patches: Expo SDK 54 (codegen 0.81.5) + React Native 0.86.
// RN 0.86 introduces Flow event types in internal components that codegen@0.81.5
// cannot parse. Instead of crashing, we make the parser return empty event args.
//
// #1118 — fail loud : un patch REQUIS qui ne peut pas s'appliquer (fichier
// absent ou chaîne cible introuvable après un bump de dépendance) fait échouer
// l'install (exit 1) au lieu de produire un crash différé et incompréhensible
// au bundle/runtime. Seul le patch DebuggingOverlay (spécifique simulateur
// iOS 26 beta, non critique) reste optionnel.
//
// Contexte, tableau des patches et stratégie de sortie :
// docs/expo54-rn086-compat.md
const fs = require('fs');
const path = require('path');

/**
 * @returns {"patched" | "already" | "missing-file" | "target-not-found"}
 */
function patch(filePath, targetStr, replacementStr, markerStr) {
  if (!fs.existsSync(filePath)) {
    return 'missing-file';
  }
  const content = fs.readFileSync(filePath, 'utf8');
  if (content.includes(markerStr)) {
    console.log(`[postinstall-patch] Already patched: ${path.basename(filePath)}`);
    return 'already';
  }
  if (!content.includes(targetStr)) {
    return 'target-not-found';
  }
  fs.writeFileSync(filePath, content.replace(targetStr, replacementStr));
  console.log(`[postinstall-patch] Patched: ${path.basename(filePath)}`);
  return 'patched';
}

const errorUtilsPath = path.join(
  __dirname,
  '../node_modules/@react-native/codegen/lib/parsers/error-utils.js'
);

/** @type {Array<{name: string, optional?: boolean, file: string, target: string, replacement: string, marker: string}>} */
const PATCHES = [
  {
    // Patch 1: babel-plugin-codegen — wrap generateViewConfig in try-catch
    // for react-native/src/private files
    name: 'babel-plugin-codegen generateViewConfig try-catch',
    file: path.join(__dirname, '../node_modules/@react-native/babel-plugin-codegen/index.js'),
    target: `if (this.defaultExport) {
            const viewConfig = generateViewConfig(this.filename, this.code);`,
    replacement: `if (this.defaultExport) {
            let viewConfig;
            try {
              viewConfig = generateViewConfig(this.filename, this.code);
            } catch (e) {
              if (this.filename && this.filename.includes('/react-native/src/private/')) {
                return;
              }
              throw e;
            }`,
    marker: `this.filename.includes('/react-native/src/private/')`,
  },
  {
    // Patch 3: DebuggingOverlay — iOS 26 beta simulator registers the
    // ViewManager but the view config is incomplete ("Invariant Violation:
    // View config not found" at startup). Dev tool only → OPTIONNEL : un
    // échec ne bloque pas l'install.
    name: 'DebuggingOverlay disable (iOS 26 beta sim)',
    optional: true,
    file: path.join(__dirname, '../node_modules/react-native/Libraries/Debugging/DebuggingOverlay.js'),
    target: `const isNativeComponentReady =
  UIManager.hasViewManagerConfig('DebuggingOverlay');`,
    replacement: `const isNativeComponentReady = false; // patched: iOS 26 beta view config incomplete`,
    marker: `patched: iOS 26 beta view config incomplete`,
  },
  {
    // Patch 2a: tolerate unresolvable event argument types
    name: 'codegen error-utils argumentProps',
    file: errorUtilsPath,
    target: `function throwIfArgumentPropsAreNull(argumentProps, eventName) {
  if (!argumentProps) {
    throw new Error(\`Unable to determine event arguments for "\${eventName}"\`);
  }
  return argumentProps;
}`,
    replacement: `function throwIfArgumentPropsAreNull(argumentProps, eventName) {
  if (!argumentProps) {
    return [];
  }
  return argumentProps;
}`,
    marker: `return [];`,
  },
  {
    // Patch 2b: tolerate unresolvable event bubbling types
    name: 'codegen error-utils bubblingType',
    file: errorUtilsPath,
    target: `function throwIfBubblingTypeIsNull(bubblingType, eventName) {
  if (!bubblingType) {
    throw new Error(
      \`Unable to determine event bubbling type for "\${eventName}"\`,
    );
  }
  return bubblingType;
}`,
    replacement: `function throwIfBubblingTypeIsNull(bubblingType, eventName) {
  if (!bubblingType) {
    return 'direct';
  }
  return bubblingType;
}`,
    marker: `return 'direct';`,
  },
];

const failures = [];
for (const p of PATCHES) {
  const status = patch(p.file, p.target, p.replacement, p.marker);
  if (status === 'missing-file' || status === 'target-not-found') {
    if (p.optional) {
      console.warn(`[postinstall-patch] OPTIONAL patch skipped (${status}): ${p.name}`);
    } else {
      failures.push({ name: p.name, file: p.file, status });
    }
  }
}

if (failures.length > 0) {
  console.error('\n[postinstall-patch] ÉCHEC — patches requis non appliqués :');
  for (const f of failures) {
    console.error(`  - ${f.name} (${f.status})\n    ${f.file}`);
  }
  console.error(
    '\nUn bump de react-native/@react-native/codegen a probablement changé le code cible.\n' +
    'Voir docs/expo54-rn086-compat.md pour mettre à jour les patches ou décider de la sortie\n' +
    '(retour RN 0.81 canonique SDK 54, ou SDK Expo supportant RN 0.86).'
  );
  process.exit(1);
}
