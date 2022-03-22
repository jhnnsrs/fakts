import useBaseUrl from "@docusaurus/useBaseUrl";
import React from "react";
import clsx from "clsx";
import styles from "./HomepageFeatures.module.css";

type FeatureItem = {
  title: string;
  image: string;
  description: JSX.Element;
};

const FeatureList: FeatureItem[] = [
  {
    title: "Single Purpose",
    image: "/img/undraw_docusaurus_mountain.svg",
    description: (
      <>
        fakts is like oauth2, but for configurations. Simply define flows to
        acquire and parse configuraiton from various sources.
      </>
    ),
  },
  {
    title: "Pydantic",
    image: "/img/undraw_docusaurus_tree.svg",
    description: <>fakts integrates well with pydantic.</>,
  },
  {
    title: "Async ready",
    image: "/img/undraw_docusaurus_react.svg",
    description: (
      <>fakts is async ready and provides a synchronous and asynchronous api</>
    ),
  },
];

function Feature({ title, image, description }: FeatureItem) {
  return (
    <div className={clsx("col col--4")}>
      <div className="text--center padding-horiz--md padding-top--md">
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): JSX.Element {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
