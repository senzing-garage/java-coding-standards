public class Outer {
    public abstract static class AbstractBuilder<E extends Outer, B extends AbstractBuilder<E, B>> implements Initializer {
    }
}
