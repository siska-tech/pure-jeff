use std::fmt;

/// What went wrong while locking, verifying or loading a model bundle. Decisions report a
/// [`Failure`](crate::Failure) instead.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum ErrorKind {
    /// The manifest or a checkpoint file is missing, unreadable, unsupported or does not match
    /// its recorded hash, shape or vocabulary.
    Bundle,
    /// The deadline passed before loading finished.
    Timeout,
    /// The process-wide compute threads differ from the bundle policy
    /// (see [`configure_threads`](crate::configure_threads)).
    ThreadConfig,
    /// An argument was rejected before any file was read.
    InvalidArgument,
    /// A worker request or response file could not be read, parsed or written.
    Io,
}

/// Error from bundle and model handling, with a kind and a human-readable message.
#[derive(Debug, Clone)]
pub struct Error {
    kind: ErrorKind,
    message: String,
}

impl Error {
    pub(crate) fn new(kind: ErrorKind, message: impl fmt::Display) -> Self {
        Self {
            kind,
            message: message.to_string(),
        }
    }
    /// Maps an internal error, reporting a timeout when the deadline has passed.
    #[cfg(feature = "native")]
    pub(crate) fn bundle(error: anyhow::Error, deadline: std::time::Instant) -> Self {
        let kind = if std::time::Instant::now() >= deadline {
            ErrorKind::Timeout
        } else {
            ErrorKind::Bundle
        };
        Self::new(kind, format!("{error:#}"))
    }
    pub fn kind(&self) -> ErrorKind {
        self.kind
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let kind = match self.kind {
            ErrorKind::Bundle => "invalid bundle",
            ErrorKind::Timeout => "deadline exceeded",
            ErrorKind::ThreadConfig => "thread configuration",
            ErrorKind::InvalidArgument => "invalid argument",
            ErrorKind::Io => "worker I/O",
        };
        write!(f, "{kind}: {}", self.message)
    }
}

impl std::error::Error for Error {}
