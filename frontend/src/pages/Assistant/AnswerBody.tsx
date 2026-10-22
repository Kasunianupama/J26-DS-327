/** Render plain answer paragraphs, headings and review lists without accepting HTML. */
import type { ReactNode } from 'react';

export function AnswerBody({ text }: { text: string }) {
  return <>{text.split(/\n\s*\n/).filter(part => part.trim()).map((part,index) => {
    const lines=part.trim().split('\n');
    const heading=lines.length>1 && /^.{1,100}:$/.test(lines[0]) ? lines.shift()!.slice(0,-1) : null;
    const content: ReactNode[]=[];let paragraph: string[]=[], bullets: string[]=[];
    function flushParagraph(){if(paragraph.length){content.push(<p key={`p${content.length}`}>{paragraph.join(' ')}</p>);paragraph=[];}}
    function flushBullets(){if(bullets.length){content.push(<ul key={`u${content.length}`}>{bullets.map((item,i)=><li key={i}>{item}</li>)}</ul>);bullets=[];}}
    for(const line of lines){
      if(line.startsWith('• ')){flushParagraph();bullets.push(line.slice(2));}
      else{flushBullets();paragraph.push(line);}
    }
    flushParagraph();flushBullets();
    return <section className={heading?'c3-answer-section':undefined} key={index}>{heading && <h4>{heading}</h4>}{content}</section>;
  })}</>;
}
