/*
 * DJCat Pro 5 incremental updater.
 *
 * Usage: updater.exe <pid> <app_dir> <exe_path> <staging_dir>
 *
 *   pid         - PID of the running DJCat process to wait for
 *   app_dir     - installation directory to overwrite
 *   exe_path    - full path to djcat.exe to relaunch
 *   staging_dir - directory containing the new version's files
 *
 * Flow:
 *   1. Wait for <pid> to exit (up to 30 s, then proceed anyway).
 *   2. Recursively copy <staging_dir> over <app_dir>, overwriting files.
 *      The running updater.exe cannot be overwritten, so it is renamed
 *      to updater.exe.old first; the .old file is cleaned up on next run.
 *   3. Remove <staging_dir>.
 *   4. Launch <exe_path>.
 */

#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

#define PATH_BUF  4096
#define WAIT_TIMEOUT_MS  30000

static FILE *g_log = NULL;
static wchar_t g_logPath[PATH_BUF];

static void logMsg(const wchar_t *fmt, ...) {
    if (!g_log) return;
    SYSTEMTIME st;
    GetLocalTime(&st);
    fwprintf(g_log, L"[%04d-%02d-%02d %02d:%02d:%02d] ",
             st.wYear, st.wMonth, st.wDay,
             st.wHour, st.wMinute, st.wSecond);
    va_list ap;
    va_start(ap, fmt);
    vfwprintf(g_log, fmt, ap);
    va_end(ap);
    fwprintf(g_log, L"\n");
    fflush(g_log);
}

static void openLog(const wchar_t *appDir) {
    wcsncpy(g_logPath, appDir, PATH_BUF - 1);
    g_logPath[PATH_BUF - 1] = L'\0';
    size_t len = wcslen(g_logPath);
    _snwprintf(g_logPath + len, PATH_BUF - len, L"\\updater.log");
    g_log = _wfopen(g_logPath, L"a");
}

static BOOL waitForProcess(DWORD pid) {
    HANDLE h = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!h) {
        logMsg(L"OpenProcess(%lu) failed (err %lu), proceeding", pid, GetLastError());
        return TRUE;
    }
    logMsg(L"Waiting for PID %lu", pid);
    DWORD result = WaitForSingleObject(h, WAIT_TIMEOUT_MS);
    CloseHandle(h);
    if (result == WAIT_OBJECT_0) {
        logMsg(L"Process exited normally");
    } else {
        logMsg(L"Wait result %lu, proceeding anyway", result);
    }
    return TRUE;
}

static BOOL deleteDirectory(const wchar_t *dir);

static BOOL deleteDirectoryContents(const wchar_t *dir) {
    wchar_t pattern[PATH_BUF];
    _snwprintf(pattern, PATH_BUF, L"%s\\*", dir);
    WIN32_FIND_DATAW fd;
    HANDLE hFind = FindFirstFileW(pattern, &fd);
    if (hFind == INVALID_HANDLE_VALUE) return TRUE;
    BOOL ok = TRUE;
    do {
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
            continue;
        wchar_t path[PATH_BUF];
        _snwprintf(path, PATH_BUF, L"%s\\%s", dir, fd.cFileName);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (!deleteDirectory(path)) ok = FALSE;
        } else {
            SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL);
            if (!DeleteFileW(path)) {
                logMsg(L"DeleteFile failed: %s (err %lu)", path, GetLastError());
                ok = FALSE;
            }
        }
    } while (FindNextFileW(hFind, &fd));
    FindClose(hFind);
    return ok;
}

static BOOL deleteDirectory(const wchar_t *dir) {
    deleteDirectoryContents(dir);
    if (!RemoveDirectoryW(dir)) {
        logMsg(L"RemoveDirectory failed: %s (err %lu)", dir, GetLastError());
        return FALSE;
    }
    return TRUE;
}

static void cleanOldUpdater(const wchar_t *appDir) {
    wchar_t oldPath[PATH_BUF];
    _snwprintf(oldPath, PATH_BUF, L"%s\\updater.exe.old", appDir);
    if (GetFileAttributesW(oldPath) != INVALID_FILE_ATTRIBUTES) {
        SetFileAttributesW(oldPath, FILE_ATTRIBUTE_NORMAL);
        if (DeleteFileW(oldPath))
            logMsg(L"Cleaned up updater.exe.old");
        else
            logMsg(L"Could not delete updater.exe.old (err %lu)", GetLastError());
    }
}

static BOOL copyTree(const wchar_t *src, const wchar_t *dst, const wchar_t *appDir) {
    CreateDirectoryW(dst, NULL);
    wchar_t pattern[PATH_BUF];
    _snwprintf(pattern, PATH_BUF, L"%s\\*", src);
    WIN32_FIND_DATAW fd;
    HANDLE hFind = FindFirstFileW(pattern, &fd);
    if (hFind == INVALID_HANDLE_VALUE) {
        logMsg(L"FindFirstFile failed: %s (err %lu)", pattern, GetLastError());
        return FALSE;
    }
    BOOL ok = TRUE;
    do {
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
            continue;
        wchar_t srcPath[PATH_BUF], dstPath[PATH_BUF];
        _snwprintf(srcPath, PATH_BUF, L"%s\\%s", src, fd.cFileName);
        _snwprintf(dstPath, PATH_BUF, L"%s\\%s", dst, fd.cFileName);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (!copyTree(srcPath, dstPath, appDir)) ok = FALSE;
        } else {
            /* Handle the running updater: rename it before overwriting. */
            wchar_t oldPath[PATH_BUF];
            BOOL renamedUpdater = FALSE;
            if (_wcsicmp(fd.cFileName, L"updater.exe") == 0 &&
                _wcsicmp(dst, appDir) == 0) {
                _snwprintf(oldPath, PATH_BUF, L"%s\\updater.exe.old", appDir);
                oldPath[PATH_BUF - 1] = L'\0';
                DeleteFileW(oldPath);
                renamedUpdater = MoveFileW(dstPath, oldPath);
                if (renamedUpdater)
                    logMsg(L"Renamed running updater to updater.exe.old");
                else
                    logMsg(L"Could not rename running updater (err %lu)",
                           GetLastError());
            }
            if (!CopyFileW(srcPath, dstPath, FALSE)) {
                logMsg(L"CopyFile failed: %s -> %s (err %lu)",
                       srcPath, dstPath, GetLastError());
                ok = FALSE;
                /* Put the running updater back. Without this the app directory
                   is left with no updater.exe at all, and since DJCat deletes
                   updater.exe.old on its next start, every later Client Update
                   fails on a missing updater with nothing left to recover. */
                if (renamedUpdater) {
                    if (MoveFileW(oldPath, dstPath))
                        logMsg(L"Restored updater.exe from updater.exe.old");
                    else
                        logMsg(L"Could not restore updater.exe (err %lu)",
                               GetLastError());
                }
            }
        }
    } while (FindNextFileW(hFind, &fd));
    FindClose(hFind);
    return ok;
}

int wmain(int argc, wchar_t *argv[]) {
    if (argc < 5) {
        fwprintf(stderr, L"Usage: updater.exe <pid> <app_dir> <exe_path> <staging_dir>\n");
        return 1;
    }

    DWORD pid = (DWORD)_wtoi(argv[1]);
    const wchar_t *appDir = argv[2];
    const wchar_t *exePath = argv[3];
    const wchar_t *stagingDir = argv[4];

    openLog(appDir);
    logMsg(L"=== DJCat updater started ===");
    logMsg(L"PID=%lu appDir=%s exe=%s staging=%s", pid, appDir, exePath, stagingDir);

    cleanOldUpdater(appDir);
    waitForProcess(pid);
    Sleep(500);

    logMsg(L"Copying files from staging");
    BOOL copyOk = copyTree(stagingDir, appDir, appDir);
    if (copyOk) {
        logMsg(L"File copy succeeded");
    } else {
        logMsg(L"Some files failed to copy");
    }

    logMsg(L"Removing staging directory");
    deleteDirectory(stagingDir);

    logMsg(L"Launching %s", exePath);
    STARTUPINFOW si = { .cb = sizeof(si) };
    PROCESS_INFORMATION pi = {0};
    if (CreateProcessW(exePath, NULL, NULL, NULL, FALSE, 0, NULL, appDir, &si, &pi)) {
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
        logMsg(L"Launch succeeded");
    } else {
        logMsg(L"CreateProcess failed (err %lu), trying ShellExecute", GetLastError());
        ShellExecuteW(NULL, L"open", exePath, NULL, appDir, SW_SHOWNORMAL);
    }

    logMsg(L"=== Updater finished ===\n");
    if (g_log) fclose(g_log);
    return copyOk ? 0 : 1;
}
