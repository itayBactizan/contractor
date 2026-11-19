// One result image with a title, optional details and a download button.
export default function ImageCard({ title, imageUrl, downloadName, children }) {
  return (
    <div className="card">
      <a href={imageUrl} target="_blank" rel="noreferrer" title="Open full size">
        <img src={imageUrl} alt={title} loading="lazy" />
      </a>
      <div className="card-footer">
        <div className="card-text">
          <span className="card-id">{title}</span>
          {children}
        </div>
        <a className="button" href={imageUrl} download={downloadName}>
          Download
        </a>
      </div>
    </div>
  )
}
