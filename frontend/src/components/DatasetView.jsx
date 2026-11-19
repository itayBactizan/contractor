import { useState } from 'react'
import CategorySection from './CategorySection.jsx'

// "Dataset (YOLO)" tab: random contracts by MataraDesc saved as clean training images
export default function DatasetView() {
  const [datasetSize, setDatasetSize] = useState(null)

  return (
    <>
      <p className="subtitle">
        Build a YOLO image dataset: 1024×1024 images, everything outside the contract black, no lines or numbers.
        Small contracts are enlarged to fill the image (at most 4×, with high-quality resampling); contracts
        larger than 205 m are split into several full-detail images. Images are saved to{' '}
        <code>dataset/images</code> with
        their metadata in <code>dataset/meta</code> and <code>dataset/metadata.csv</code>. Contracts already in
        the dataset are never picked again.
      </p>
      {datasetSize !== null && (
        <p className="dataset-size">
          Dataset size: <strong>{datasetSize}</strong> images
        </p>
      )}
      <CategorySection
        layer="contracts"
        title="Contracts"
        kind="contract"
        fields={['MataraDesc']}
        idPrefix="dataset"
        sampleUrl="/api/dataset/sample"
        onResults={(data) => setDatasetSize(data.dataset_size)}
      />
    </>
  )
}
