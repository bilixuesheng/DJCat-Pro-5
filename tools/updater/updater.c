/*
 * DJCat Pro 5 Client Update installer.
 *
 * Usage: updater.exe <pid> <app_dir> <exe_path> <staging_dir>
 *
 *   pid         - PID of the DJCat process to wait for
 *   app_dir     - installation directory to replace
 *   exe_path    - full path to djcat.exe, relaunched once the update lands
 *   staging_dir - directory holding the already extracted new version
 *
 * The install is a directory swap, not a per-file copy: the staged tree is
 * renamed next to app_dir, app_dir is renamed aside as a backup, and the staged
 * tree takes its place. Every step is a same-volume rename, so there is never a
 * half-updated directory and any failure puts the backup back. A per-file copy
 * has no such property: one failed file leaves the install in a state nothing
 * can recover, and the file that fails may be the updater's own image.
 *
 * The swap-with-rollback and relocate-out-of-the-target ideas come from
 * Ghost-Downloader-3's updater (GPL-3.0), like this project's download worker.
 * Two things are deliberately NOT copied from it:
 *
 *   - Ghost copies its portable folder into the new tree. DJCat's Portable Mode
 *     keeps the App Data Directory at app_dir\DJCatPro, which holds installed
 *     Applications and the Application Store cache and is routinely gigabytes,
 *     so it is renamed into the staged tree instead. A rename is instant and,
 *     unlike a copy, cannot half-finish.
 *   - Ghost's macOS/Linux branches are dropped; DJCat is Windows only.
 *
 * Elevation is kept, and so is the de-elevation that must go with it. The
 * installer is PrivilegesRequired=lowest, but the release also ships a ZIP that
 * can be extracted anywhere, including a protected directory. Such an install
 * already falls back to the per-user App Data Directory (see
 * app/config/paths.py), and without elevation its Client Update could never
 * land at all.
 */

#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

#define PATH_BUF 4096
#define WAIT_TIMEOUT_MS 30000
#define RENAME_RETRIES 10
#define RENAME_RETRY_MS 200

enum {
    EXIT_OK = 0,
    EXIT_BAD_ARGS = 1,
    EXIT_STAGING_INVALID = 2,
    EXIT_NOT_WRITABLE = 3,
    EXIT_SWAP_FAILED = 4,
    EXIT_LAUNCH_FAILED = 5,
};

static FILE *g_log = NULL;
static wchar_t g_logPath[PATH_BUF];

/* _snwprintf does not terminate on truncation; every path goes through here. */
static void formatPath(wchar_t *out, size_t size, const wchar_t *format, ...) {
    va_list ap;
    va_start(ap, format);
    _vsnwprintf(out, size, format, ap);
    va_end(ap);
    out[size - 1] = L'\0';
}

static void logMsg(const wchar_t *format, ...) {
    if (!g_log) return;
    SYSTEMTIME st;
    GetLocalTime(&st);
    fwprintf(g_log, L"[%04d-%02d-%02d %02d:%02d:%02d] ",
             st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
    va_list ap;
    va_start(ap, format);
    vfwprintf(g_log, format, ap);
    va_end(ap);
    fwprintf(g_log, L"\n");
    fflush(g_log);
}

static void openLog(const wchar_t *directory) {
    formatPath(g_logPath, PATH_BUF, L"%ls\\updater.log", directory);
    g_log = _wfopen(g_logPath, L"a");
}

static void closeLog(void) {
    if (g_log) {
        fclose(g_log);
        g_log = NULL;
    }
}

static BOOL hasDir(const wchar_t *path) {
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES &&
           (attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static BOOL hasFile(const wchar_t *path) {
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES &&
           !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static void directoryOf(wchar_t *path) {
    wchar_t *slash = wcsrchr(path, L'\\');
    wchar_t *forward = wcsrchr(path, L'/');
    if (forward > slash) slash = forward;
    if (slash) *slash = L'\0';
}

/* Callers may hand us forward slashes; Win32 accepts them but a prefix compare
   against GetModuleFileNameW's backslashes would not match, which would silently
   skip the relocation this design depends on. */
static void normalizeSeparators(wchar_t *path) {
    for (wchar_t *cursor = path; *cursor; cursor++)
        if (*cursor == L'/') *cursor = L'\\';
}

static void stripTrailingSlashes(wchar_t *path) {
    size_t length = wcslen(path);
    while (length > 1 && (path[length - 1] == L'\\' || path[length - 1] == L'/'))
        path[--length] = L'\0';
}

static const wchar_t *baseNameOf(const wchar_t *path) {
    const wchar_t *slash = wcsrchr(path, L'\\');
    const wchar_t *forward = wcsrchr(path, L'/');
    if (forward > slash) slash = forward;
    return slash ? slash + 1 : path;
}

static BOOL deleteTree(const wchar_t *directory);

static void deleteTreeContents(const wchar_t *directory) {
    wchar_t pattern[PATH_BUF];
    formatPath(pattern, PATH_BUF, L"%ls\\*", directory);
    WIN32_FIND_DATAW found;
    HANDLE search = FindFirstFileW(pattern, &found);
    if (search == INVALID_HANDLE_VALUE) return;
    do {
        if (wcscmp(found.cFileName, L".") == 0 || wcscmp(found.cFileName, L"..") == 0)
            continue;
        wchar_t path[PATH_BUF];
        formatPath(path, PATH_BUF, L"%ls\\%ls", directory, found.cFileName);
        if (found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            deleteTree(path);
        } else {
            SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL);
            DeleteFileW(path);
        }
    } while (FindNextFileW(search, &found));
    FindClose(search);
}

static BOOL deleteTree(const wchar_t *directory) {
    if (!hasDir(directory)) return TRUE;
    deleteTreeContents(directory);
    return RemoveDirectoryW(directory);
}

/* Anti-virus and indexers hold brief handles on a tree that was just written. */
static BOOL moveTree(const wchar_t *from, const wchar_t *to) {
    for (int attempt = 0; attempt < RENAME_RETRIES; attempt++) {
        if (MoveFileW(from, to)) return TRUE;
        DWORD error = GetLastError();
        if (error != ERROR_ACCESS_DENIED && error != ERROR_SHARING_VIOLATION) {
            logMsg(L"move \"%ls\" -> \"%ls\" failed (err %lu)", from, to, error);
            return FALSE;
        }
        Sleep(RENAME_RETRY_MS);
    }
    logMsg(L"move \"%ls\" -> \"%ls\" still locked after %d tries",
           from, to, RENAME_RETRIES);
    return FALSE;
}

static BOOL canWriteDir(const wchar_t *directory) {
    wchar_t probe[PATH_BUF];
    formatPath(probe, PATH_BUF, L"%ls\\.djcat-update-probe", directory);
    HANDLE handle = CreateFileW(
        probe, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
        FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
    if (handle == INVALID_HANDLE_VALUE) return FALSE;
    CloseHandle(handle);
    return TRUE;
}

static BOOL isElevated(void) {
    HANDLE token = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return FALSE;
    TOKEN_ELEVATION elevation = {0};
    DWORD size = 0;
    BOOL elevated = GetTokenInformation(token, TokenElevation, &elevation,
                                        sizeof(elevation), &size) &&
                    elevation.TokenIsElevated;
    CloseHandle(token);
    return elevated;
}

/* Re-launch through UAC with the same arguments. FALSE means the prompt was
   declined or could not be shown, which is a reason to report, not to retry. */
static BOOL restartElevated(int argc, wchar_t **argv) {
    wchar_t selfPath[PATH_BUF];
    if (!GetModuleFileNameW(NULL, selfPath, PATH_BUF)) return FALSE;
    selfPath[PATH_BUF - 1] = L'\0';

    wchar_t parameters[PATH_BUF * 2];
    parameters[0] = L'\0';
    for (int index = 1; index < argc; index++) {
        wchar_t argument[PATH_BUF];
        formatPath(argument, PATH_BUF,
                   index == 1 ? L"\"%ls\"" : L" \"%ls\"", argv[index]);
        wcsncat(parameters, argument, PATH_BUF * 2 - wcslen(parameters) - 1);
    }

    SHELLEXECUTEINFOW info = {0};
    info.cbSize = sizeof(info);
    info.fMask = SEE_MASK_NOCLOSEPROCESS;
    info.lpVerb = L"runas";
    info.lpFile = selfPath;
    info.lpParameters = parameters;
    info.nShow = SW_HIDE;
    if (!ShellExecuteExW(&info)) return FALSE;
    if (info.hProcess) CloseHandle(info.hProcess);
    return TRUE;
}

/*
 * Relaunch DJCat with the logged-in user's token by borrowing Explorer's.
 *
 * This is not optional once the updater can elevate. A CreateProcess from an
 * elevated updater hands DJCat an administrator token, and everything it writes
 * afterwards -- UserConfig.json, the Program directory holding installed
 * Applications, the Application Store cache -- ends up owned by the
 * administrator, so the next ordinary run cannot read its own data. That is a
 * worse and far more confusing failure than the one elevation fixes.
 */
static BOOL startAppAsUser(const wchar_t *exePath, const wchar_t *workingDir) {
    HWND tray = FindWindowW(L"Shell_TrayWnd", NULL);
    if (!tray) return FALSE;
    DWORD shellPid = 0;
    GetWindowThreadProcessId(tray, &shellPid);
    if (!shellPid) return FALSE;

    HANDLE shell = OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, shellPid);
    if (!shell) return FALSE;

    HANDLE shellToken = NULL, userToken = NULL;
    BOOL started = FALSE;
    if (OpenProcessToken(shell, TOKEN_DUPLICATE, &shellToken) &&
        DuplicateTokenEx(shellToken,
                         TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY |
                         TOKEN_ADJUST_DEFAULT | TOKEN_ADJUST_SESSIONID,
                         NULL, SecurityImpersonation, TokenPrimary, &userToken)) {
        wchar_t command[PATH_BUF];
        formatPath(command, PATH_BUF, L"\"%ls\"", exePath);
        STARTUPINFOW startup = { .cb = sizeof(startup) };
        PROCESS_INFORMATION process = {0};
        if (CreateProcessAsUserW(userToken, NULL, command, NULL, NULL, FALSE,
                                 0, NULL, workingDir, &startup, &process)) {
            CloseHandle(process.hProcess);
            CloseHandle(process.hThread);
            started = TRUE;
        }
    }
    if (userToken) CloseHandle(userToken);
    if (shellToken) CloseHandle(shellToken);
    CloseHandle(shell);
    return started;
}

static void writeFailureMarker(const wchar_t *appDir, const wchar_t *reason) {
    wchar_t path[PATH_BUF];
    formatPath(path, PATH_BUF, L"%ls\\update-failed.txt", appDir);
    FILE *marker = _wfopen(path, L"w, ccs=UTF-8");
    if (!marker) return;
    fwprintf(marker, L"%ls\n%ls\n", reason, g_logPath);
    fclose(marker);
}

static void waitForProcess(DWORD pid) {
    HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!process) {
        logMsg(L"OpenProcess(%lu) failed (err %lu), assuming it already exited",
               pid, GetLastError());
        return;
    }
    logMsg(L"waiting for pid %lu", pid);
    DWORD result = WaitForSingleObject(process, WAIT_TIMEOUT_MS);
    CloseHandle(process);
    logMsg(result == WAIT_OBJECT_0 ? L"process exited"
                                   : L"wait returned %lu, proceeding anyway", result);
}

/* True when `path` is `directory` itself or sits underneath it. */
static BOOL isInside(const wchar_t *path, const wchar_t *directory) {
    wchar_t longPath[PATH_BUF], longDir[PATH_BUF];
    if (!GetLongPathNameW(path, longPath, PATH_BUF))
        formatPath(longPath, PATH_BUF, L"%ls", path);
    if (!GetLongPathNameW(directory, longDir, PATH_BUF))
        formatPath(longDir, PATH_BUF, L"%ls", directory);
    normalizeSeparators(longPath);
    normalizeSeparators(longDir);
    stripTrailingSlashes(longDir);
    size_t length = wcslen(longDir);
    if (_wcsnicmp(longPath, longDir, length) != 0) return FALSE;
    wchar_t next = longPath[length];
    return next == L'\0' || next == L'\\' || next == L'/';
}

/*
 * Re-launch from %TEMP% when running from inside the directory about to be
 * renamed. Windows keeps the running image mapped, and the open log lives in
 * the same tree, so either one would block MoveFileW on app_dir.
 *
 * Returns 1 when a relocated copy took over and this process should exit,
 * 0 when already outside app_dir, and -1 when relocation was needed but failed.
 */
static int relocateOutOfAppDir(const wchar_t *appDir, int argc, wchar_t **argv) {
    wchar_t selfPath[PATH_BUF];
    if (!GetModuleFileNameW(NULL, selfPath, PATH_BUF)) return 0;
    selfPath[PATH_BUF - 1] = L'\0';
    if (!isInside(selfPath, appDir)) return 0;

    wchar_t tempRoot[PATH_BUF], tempDir[PATH_BUF], target[PATH_BUF];
    if (!GetTempPathW(PATH_BUF, tempRoot)) return -1;
    formatPath(tempDir, PATH_BUF, L"%ls%ls", tempRoot, L"djcat_updater");
    CreateDirectoryW(tempDir, NULL);
    formatPath(target, PATH_BUF, L"%ls\\updater.exe", tempDir);

    /* A copy left by an earlier update is still mapped only while it runs. */
    DeleteFileW(target);
    if (!CopyFileW(selfPath, target, FALSE)) return -1;

    wchar_t command[PATH_BUF * 2];
    formatPath(command, PATH_BUF * 2, L"\"%ls\"", target);
    for (int index = 1; index < argc; index++) {
        wchar_t argument[PATH_BUF];
        formatPath(argument, PATH_BUF, L" \"%ls\"", argv[index]);
        wcsncat(command, argument, PATH_BUF * 2 - wcslen(command) - 1);
    }

    STARTUPINFOW startup = { .cb = sizeof(startup) };
    PROCESS_INFORMATION process = {0};
    if (!CreateProcessW(target, command, NULL, NULL, FALSE,
                        CREATE_NEW_PROCESS_GROUP, NULL, tempDir,
                        &startup, &process))
        return -1;
    CloseHandle(process.hProcess);
    CloseHandle(process.hThread);
    return 1;
}

/*
 * Swap the staged tree into place.
 *
 * Only renames, so the window in which app_dir does not exist is as short as
 * the file system can make it, and every failure has an exact inverse.
 */
static BOOL installStagedTree(const wchar_t *appDir, const wchar_t *stagedDir,
                              const wchar_t *backupDir, BOOL hasPortableData) {
    wchar_t portableInApp[PATH_BUF], portableInStaged[PATH_BUF];
    formatPath(portableInApp, PATH_BUF, L"%ls\\DJCatPro", appDir);
    formatPath(portableInStaged, PATH_BUF, L"%ls\\DJCatPro", stagedDir);

    if (hasPortableData) {
        logMsg(L"carrying the portable App Data Directory into the new tree");
        if (!moveTree(portableInApp, portableInStaged)) return FALSE;
    }

    if (!moveTree(appDir, backupDir)) {
        if (hasPortableData) moveTree(portableInStaged, portableInApp);
        return FALSE;
    }

    if (!moveTree(stagedDir, appDir)) {
        logMsg(L"rolling the backup back into place");
        if (!moveTree(backupDir, appDir))
            logMsg(L"BACKUP COULD NOT BE RESTORED, it is still at \"%ls\"", backupDir);
        else if (hasPortableData)
            moveTree(portableInStaged, portableInApp);
        return FALSE;
    }
    return TRUE;
}

int wmain(int argc, wchar_t *argv[]) {
    if (argc < 5) {
        fwprintf(stderr,
                 L"Usage: updater.exe <pid> <app_dir> <exe_path> <staging_dir>\n");
        return EXIT_BAD_ARGS;
    }

    DWORD pid = (DWORD)_wtoi(argv[1]);
    wchar_t appDir[PATH_BUF], exePath[PATH_BUF], stagingDir[PATH_BUF];
    formatPath(appDir, PATH_BUF, L"%ls", argv[2]);
    formatPath(exePath, PATH_BUF, L"%ls", argv[3]);
    formatPath(stagingDir, PATH_BUF, L"%ls", argv[4]);
    normalizeSeparators(appDir);
    normalizeSeparators(exePath);
    normalizeSeparators(stagingDir);
    stripTrailingSlashes(appDir);
    stripTrailingSlashes(stagingDir);

    int relocated = relocateOutOfAppDir(appDir, argc, argv);
    if (relocated > 0) return EXIT_OK;

    wchar_t selfDir[PATH_BUF];
    if (GetModuleFileNameW(NULL, selfDir, PATH_BUF)) {
        selfDir[PATH_BUF - 1] = L'\0';
        directoryOf(selfDir);
    } else {
        formatPath(selfDir, PATH_BUF, L"%ls", appDir);
    }
    openLog(selfDir);

    logMsg(L"=== DJCat updater started ===");
    logMsg(L"pid=%lu appDir=\"%ls\" exe=\"%ls\" staging=\"%ls\"",
           pid, appDir, exePath, stagingDir);
    if (relocated < 0) {
        logMsg(L"could not relocate out of the install directory");
        writeFailureMarker(appDir, L"更新器无法从安装目录移出");
        closeLog();
        return EXIT_SWAP_FAILED;
    }

    waitForProcess(pid);

    /* The staged tree must be able to replace the install, or nothing moves. */
    wchar_t stagedExe[PATH_BUF];
    formatPath(stagedExe, PATH_BUF, L"%ls\\%ls", stagingDir, baseNameOf(exePath));
    if (!hasDir(stagingDir) || !hasFile(stagedExe)) {
        logMsg(L"staged tree has no \"%ls\", refusing to swap", stagedExe);
        writeFailureMarker(appDir, L"更新包内容不完整");
        closeLog();
        return EXIT_STAGING_INVALID;
    }

    wchar_t parentDir[PATH_BUF];
    formatPath(parentDir, PATH_BUF, L"%ls", appDir);
    directoryOf(parentDir);
    if (!canWriteDir(parentDir)) {
        if (!isElevated()) {
            logMsg(L"\"%ls\" is not writable, asking for elevation", parentDir);
            closeLog();
            /* The elevated copy runs from %TEMP%, so it does not relocate again. */
            if (restartElevated(argc, argv)) return EXIT_OK;
            openLog(selfDir);
            logMsg(L"elevation was declined or could not be started");
        } else {
            logMsg(L"\"%ls\" is not writable even when elevated", parentDir);
        }
        writeFailureMarker(appDir, L"安装目录不可写，更新未执行");
        closeLog();
        return EXIT_NOT_WRITABLE;
    }

    wchar_t stagedDir[PATH_BUF], backupDir[PATH_BUF], portableInApp[PATH_BUF];
    formatPath(stagedDir, PATH_BUF, L"%ls.new", appDir);
    formatPath(backupDir, PATH_BUF, L"%ls.backup", appDir);
    formatPath(portableInApp, PATH_BUF, L"%ls\\DJCatPro", appDir);
    deleteTree(stagedDir);
    deleteTree(backupDir);

    /* The staged tree sits under Updata\, inside the directory being renamed. */
    if (!moveTree(stagingDir, stagedDir)) {
        logMsg(L"could not move the staged tree out of the install directory");
        writeFailureMarker(appDir, L"无法移动更新包");
        closeLog();
        return EXIT_SWAP_FAILED;
    }

    BOOL hasPortableData = hasDir(portableInApp);
    BOOL installed = installStagedTree(appDir, stagedDir, backupDir, hasPortableData);

    if (!installed) {
        logMsg(L"install failed, the previous version is untouched");
        writeFailureMarker(appDir, L"更新安装失败，已保留原版本");
        deleteTree(stagedDir);
    } else {
        logMsg(L"installed");
        if (!deleteTree(backupDir))
            logMsg(L"could not remove \"%ls\", it is safe to delete by hand",
                   backupDir);
    }

    logMsg(L"launching \"%ls\"", exePath);
    STARTUPINFOW startup = { .cb = sizeof(startup) };
    PROCESS_INFORMATION process = {0};
    int status = installed ? EXIT_OK : EXIT_SWAP_FAILED;
    if (isElevated() && startAppAsUser(exePath, appDir)) {
        logMsg(L"relaunched DJCat with the logged-in user's token");
    } else if (CreateProcessW(exePath, NULL, NULL, NULL, FALSE, 0, NULL, appDir,
                              &startup, &process)) {
        CloseHandle(process.hProcess);
        CloseHandle(process.hThread);
    } else {
        logMsg(L"CreateProcess failed (err %lu), falling back to ShellExecute",
               GetLastError());
        if ((INT_PTR)ShellExecuteW(NULL, L"open", exePath, NULL, appDir,
                                   SW_SHOWNORMAL) <= 32) {
            logMsg(L"could not relaunch DJCat");
            status = EXIT_LAUNCH_FAILED;
        }
    }

    logMsg(L"=== updater finished (exit %d) ===\n", status);
    closeLog();

    /* The log lives beside the relocated updater; leave a copy where users look. */
    wchar_t logInApp[PATH_BUF];
    formatPath(logInApp, PATH_BUF, L"%ls\\updater.log", appDir);
    if (_wcsicmp(logInApp, g_logPath) != 0)
        CopyFileW(g_logPath, logInApp, FALSE);
    return status;
}
