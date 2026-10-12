// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.export;

import android.content.Intent;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.provider.DocumentsContract.Document;
import android.provider.DocumentsContract.Root;
import android.provider.DocumentsProvider;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.Arrays;

/**
 * A documents provider over a folder of the test package ({@code files/documents}), for the
 * export's SAF tests. Like the system's, it never overwrites: a taken name gets " (1)". Its extra
 * calls: {@link #GRANT} gives the caller the tree, {@link #RESET} empties the folder,
 * {@link #PUT} adds a file of a given size.
 *
 * <p>Java on purpose: it runs in the test APK's own process, which has no Kotlin runtime.
 */
public class TestDocumentsProvider extends DocumentsProvider {
    public static final String AUTHORITY = "com.qtekfun.ultimatetunes.test.documents";
    public static final String ROOT = "root";
    public static final String GRANT = "test:grant";
    public static final String RESET = "test:reset";
    public static final String PUT = "test:put";
    public static final String SIZE = "size";

    private static final String[] ROOT_COLUMNS = {
        Root.COLUMN_ROOT_ID, Root.COLUMN_DOCUMENT_ID, Root.COLUMN_TITLE, Root.COLUMN_FLAGS
    };
    private static final String[] DOCUMENT_COLUMNS = {
        Document.COLUMN_DOCUMENT_ID,
        Document.COLUMN_DISPLAY_NAME,
        Document.COLUMN_MIME_TYPE,
        Document.COLUMN_SIZE,
        Document.COLUMN_FLAGS
    };

    private File base() {
        File base = new File(getContext().getFilesDir(), "documents");
        base.mkdirs();
        return base;
    }

    private File fileOf(String id) throws FileNotFoundException {
        if (!id.equals(ROOT) && !id.startsWith(ROOT + "/")) {
            throw new FileNotFoundException("unknown document " + id);
        }
        String relative = id.substring(ROOT.length());
        return relative.isEmpty() ? base() : new File(base(), relative.substring(1));
    }

    private String idOf(File file) {
        String basePath = base().getAbsolutePath();
        String path = file.getAbsolutePath();
        return path.equals(basePath) ? ROOT : ROOT + path.substring(basePath.length());
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public Bundle call(String method, String arg, Bundle extras) {
        switch (method) {
            case GRANT:
                Uri tree = DocumentsContract.buildTreeDocumentUri(AUTHORITY, ROOT);
                getContext().grantUriPermission(
                        getCallingPackage(),
                        tree,
                        Intent.FLAG_GRANT_READ_URI_PERMISSION
                                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                                | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
                return new Bundle();
            case RESET:
                deleteAll(base());
                return new Bundle();
            case PUT:
                File file = new File(base(), arg);
                file.getParentFile().mkdirs();
                try (FileOutputStream out = new FileOutputStream(file)) {
                    out.write(new byte[extras.getInt(SIZE)]);
                } catch (IOException e) {
                    throw new IllegalStateException(e);
                }
                return new Bundle();
            default:
                return super.call(method, arg, extras);
        }
    }

    private static void deleteAll(File file) {
        File[] children = file.listFiles();
        if (children != null) {
            for (File child : children) {
                deleteAll(child);
            }
        }
        file.delete();
    }

    @Override
    public Cursor queryRoots(String[] projection) {
        MatrixCursor cursor = new MatrixCursor(projection != null ? projection : ROOT_COLUMNS);
        cursor.newRow()
                .add(Root.COLUMN_ROOT_ID, ROOT)
                .add(Root.COLUMN_DOCUMENT_ID, ROOT)
                .add(Root.COLUMN_TITLE, "Test")
                .add(Root.COLUMN_FLAGS, Root.FLAG_SUPPORTS_CREATE | Root.FLAG_SUPPORTS_IS_CHILD);
        return cursor;
    }

    @Override
    public Cursor queryDocument(String documentId, String[] projection)
            throws FileNotFoundException {
        MatrixCursor cursor = new MatrixCursor(projection != null ? projection : DOCUMENT_COLUMNS);
        row(cursor, fileOf(documentId));
        return cursor;
    }

    @Override
    public Cursor queryChildDocuments(String parentId, String[] projection, String sortOrder)
            throws FileNotFoundException {
        MatrixCursor cursor = new MatrixCursor(projection != null ? projection : DOCUMENT_COLUMNS);
        File[] children = fileOf(parentId).listFiles();
        if (children != null) {
            Arrays.sort(children);
            for (File child : children) {
                row(cursor, child);
            }
        }
        return cursor;
    }

    private void row(MatrixCursor cursor, File file) throws FileNotFoundException {
        if (!file.exists()) {
            throw new FileNotFoundException(file.getName());
        }
        boolean folder = file.isDirectory();
        cursor.newRow()
                .add(Document.COLUMN_DOCUMENT_ID, idOf(file))
                .add(Document.COLUMN_DISPLAY_NAME, file.getName())
                .add(
                        Document.COLUMN_MIME_TYPE,
                        folder ? Document.MIME_TYPE_DIR : "application/octet-stream")
                .add(Document.COLUMN_SIZE, folder ? null : file.length())
                .add(
                        Document.COLUMN_FLAGS,
                        Document.FLAG_SUPPORTS_DELETE
                                | Document.FLAG_SUPPORTS_RENAME
                                | Document.FLAG_SUPPORTS_WRITE
                                | (folder ? Document.FLAG_DIR_SUPPORTS_CREATE : 0));
    }

    @Override
    public String createDocument(String parentId, String mimeType, String displayName)
            throws FileNotFoundException {
        File file = unique(fileOf(parentId), displayName);
        try {
            if (Document.MIME_TYPE_DIR.equals(mimeType)) {
                file.mkdirs();
            } else {
                file.createNewFile();
            }
        } catch (IOException e) {
            throw new FileNotFoundException(e.getMessage());
        }
        return idOf(file);
    }

    @Override
    public String renameDocument(String documentId, String displayName)
            throws FileNotFoundException {
        File before = fileOf(documentId);
        File after = unique(before.getParentFile(), displayName);
        if (!before.renameTo(after)) {
            throw new FileNotFoundException("cannot rename " + documentId);
        }
        String id = idOf(after);
        return id.equals(documentId) ? null : id;
    }

    @Override
    public void deleteDocument(String documentId) throws FileNotFoundException {
        deleteAll(fileOf(documentId));
    }

    @Override
    public boolean isChildDocument(String parentId, String documentId) {
        return documentId.startsWith(parentId + "/");
    }

    @Override
    public ParcelFileDescriptor openDocument(
            String documentId, String mode, CancellationSignal signal)
            throws FileNotFoundException {
        return ParcelFileDescriptor.open(fileOf(documentId), ParcelFileDescriptor.parseMode(mode));
    }

    private static File unique(File folder, String name) {
        File first = new File(folder, name);
        if (!first.exists()) {
            return first;
        }
        int dot = name.lastIndexOf('.');
        String stem = dot > 0 ? name.substring(0, dot) : name;
        String ext = dot > 0 ? name.substring(dot) : "";
        for (int n = 1; ; n++) {
            File candidate = new File(folder, stem + " (" + n + ")" + ext);
            if (!candidate.exists()) {
                return candidate;
            }
        }
    }
}
