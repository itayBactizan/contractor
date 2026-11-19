import CategorySection from './CategorySection.jsx'

// "By category" tab: contracts by MataraDesc, plots by TARGUMYEUD or KVUZ_TRG
export default function CategoryView() {
  return (
    <>
      <p className="subtitle">
        Choose a category value and get images of random contracts or plots with that value, one image each.
      </p>
      <div className="category-sections">
        <CategorySection layer="contracts" title="Contracts" kind="contract" fields={['MataraDesc']} />
        <CategorySection layer="plots" title="Plots" kind="plot" fields={['TARGUMYEUD', 'KVUZ_TRG']} />
      </div>
    </>
  )
}
